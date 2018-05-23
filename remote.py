import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
import importlib
import json
import os
from os.path import basename, isdir, exists, split, normpath, basename, relpath, join
import sys
import tarfile
import tempfile
import time
import traceback

import boto3
import requests


@contextmanager
def stdout_redirect(stream):
    """
    Helper to redirect stdout in python2 and python3
    """
    old_stdout = sys.stdout
    sys.stdout = stream
    try:
        yield
    finally:
        sys.stdout = old_stdout


class RemoteExperiment(object):
    """
    - Start a configured EC2 Instance
    - Set up experiment environment
    - Run Experiment
    - Notify about completion
    - Upload results to S3
    - Shutdown instance
    """

    ARG_TO_ENV_VAR = [
        ('docker', '_EXPERIMENT_DOCKER_REPO'),
        ('git', '_EXPERIMENT_GIT_REPO'),
        ('branch', '_EXPERIMENT_GIT_BRANCH'),
        ('notify', '_EXPERIMENT_NOTIFICATION_URL'),
        ('log_path', '_EXPERIMENT_LOG_PATH'),
        ('results_path', '_EXPERIMENT_RESULT_PATH'),
        ('instance', '_EXPERIMENT_INSTANCE_ID'),
        ('module', '_EXPERIMENT_MODULE'),
        ('name', '_EXPERIMENT_NAME'),
        ('bucket', '_EXPERIMENT_S3_BUCKET')
    ]

    def __init__(self, args):
        self.args = deepcopy(vars(args))
        self.instance_id = self.args['instance']
        self.ec2_connection = self.get_connection()
        
        actions = self.args['action']
        user = self.args['user']

        # actions called from workstation
        if 'create' in actions:
            assert self.instance_id is None, 'May not provide instance with action "create".'
            launch_spec_path = self.args['launchspec']
            assert exists(launch_spec_path), 'Path to launch specification not found'
            self.create_spot_instance(launch_spec_path)
            self.args['instance'] = self.instance_id
        if 'start' in actions:
            self.start_instance()
        if 'setup' in actions:
            self.setup_instance(user)
        if 'experiment' in actions:
            notify = self.args['notify']
            self.run_experiment(notify, user)
        if 'stop' in actions:
            self.stop_instance()
        if 'terminate' in actions:
            self.terminate_instance()
        if '_experiment' in actions:
            self._run_experiment(
                self.args['module'], 
                self.args['bucket'],
                self.args['results_path'],
                self.args['log_path'],
                self.args['name'])

    # Functions called from workstation.
    def get_connection(self, resource_type='ec2'):
        if 'AWS_DEFAULT_REGION' in os.environ:
            region = os.environ['AWS_DEFAULT_REGION']
        else:
            region = None
        conn = boto3.client(
            resource_type,
            verify=True,
            region_name=region
        )
        return conn

    def create_spot_instance(self, launch_spec_path):
        """
        Requests a spot instance using launchSpecification.json and returns instance id.
        """
        print('Requesting spot instance...')
        ec2 = self.ec2_connection or self.get_connection()
        with open(launch_spec_path) as f:
            launch_specification = json.load(f)
        response = ec2.request_spot_instances(
            DryRun=False,
            InstanceCount=1,
            Type='one-time',
            LaunchSpecification=launch_specification
        )
        self.spot_request_id = response['SpotInstanceRequests'][0]['SpotInstanceRequestId']
        self.instance_id = self.get_instance_from_spot_request(self.spot_request_id)
        return self.instance_id

    def get_instance_from_spot_request(self, spot_request_id, timeout=15):
        ec2 = self.ec2_connection or self.get_connection()
        response = None
        time_start = time.time()
        while time.time() - time_start < timeout:
            try:
                response = ec2.describe_spot_instance_requests(
                    SpotInstanceRequestIds=[spot_request_id]
                )
                self.instance_id = response['SpotInstanceRequests'][0]['InstanceId']
                break
            except:
                time.sleep(0.3)
        if self.instance_id:
            return self.instance_id
        else:
            print('Describe spot instances response:', response)
            raise Exception(
                'Could not determine instance ID for spot request {} within specified timeout period.'.format(spot_request_id))

    def start_instance(self):
        ec2 = self.ec2_connection or self.get_connection()
        response = ec2.start_instances(InstanceIds=[self.instance_id])
        print('Start instance response:', response)

    def stop_instance(self):
        ec2 = self.ec2_connection or self.get_connection()
        response = ec2.stop_instances(InstanceIds=[self.instance_id])
        print('Stop instance response:', response)

    def terminate_instance(self):
        ec2 = self.ec2_connection or self.get_connection()
        response = ec2.terminate_instances(InstanceIds=[self.instance_id])
        try:
            self.instance_id = response['TerminatingInstances'][0]['InstanceId']
            print('Terminated instance:', self.instance_id)
        except:
            print('Terminate instance response:', response)

    def setup_instance(self, user=None):
        ec2 = self.ec2_connection or self.get_connection()
        print('Waiting for instance to start...')
        waiter = ec2.get_waiter('instance_running')
        waiter.wait(InstanceIds=[self.instance_id])
        print('Instance running.')
        print('Waiting for instance checks to complete...')
        waiter = ec2.get_waiter('instance_status_ok')
        waiter.wait(InstanceIds=[self.instance_id])
        print('Instance checks complete.')
        self.__exec_shell_script_via_ssl('setup_instance', user)
        print('Instance setup completed.')

    def run_experiment(self, notify=None, user=None):
        print('Starting experiment...')
        self.__exec_shell_script_via_ssl('run_experiment', user)
        print('Experiment started.')

    # internal functions
    def __exec_shell_script_via_ssl(self, script, user=None):
        ec2 = self.ec2_connection or self.get_connection()
        response = ec2.describe_instances(InstanceIds=[self.instance_id])
        if not response['Reservations']:
            raise Exception('Instance {} not found'.format(self.instance_id))
        try:
            # try to find private IP address and connect to it
            connect_to = response['Reservations'][0]['Instances'][0]['PrivateIpAddress']
        except:
            # assume self.instance_id to be IP
            connect_to = self.instance_id
        if user:
            connect_to = '{0}@{1}'.format(user, connect_to)
        environment_variables = self.__set_env_str()
        print('Connecting to {} using ssh'.format(connect_to))
        print('Setting environment variables:')
        print(environment_variables)
        command = '(echo "{0}" | cat - $(which {1})) |ssh -to "StrictHostKeyChecking no" {2}'
        command = command.format(environment_variables, script, connect_to)
        os.system(command)

    def __set_env_str(self):
        def set_var(var, val):
            return 'export {}=\'{}\''.format(var, val)
        set_var_list = []
        for arg, var in self.__class__.ARG_TO_ENV_VAR:
            if self.args[arg]:
                set_var_str = set_var(var, self.args[arg])
                set_var_list.append(set_var_str)
        return '; '.join(set_var_list)

    def __notify(self, status, experiment_name, runtime_in_minutes=0):
        if self.args['notify']:
            res = requests.post(self.args['notify'], data={
                'value1': '{} ({})'.format(experiment_name, self.instance_id),
                'value2': status,
                'value3': runtime_in_minutes
            })
    
    def __upload_files(self, files_to_upload, base_key, s3_bucket, tar=True):
        s3 = self.get_connection('s3')
        if tar:
            tmp_file_path = '/var/tmp/experiment_results.tar.gz'
            with tarfile.open(tmp_file_path, mode="w:gz") as f:
                for file_or_dir in files_to_upload:
                    short_name = join(base_key, basename(normpath(file_or_dir)))
                    f.add(file_or_dir, arcname=short_name)
            key = base_key + '.tar.gz'
            s3.upload_file(tmp_file_path, Bucket=s3_bucket, Key=key)
        else:
            for path in files_to_upload:
                if isdir(path):
                    root_dir = normpath(path)
                    base_dir_name = basename(root_dir)
                    for (dirpath, dirnames, filenames) in os.walk(path):
                        for name in filenames:
                            rel_dir = relpath(dirpath, root_dir)
                            rel_dir = normpath(rel_dir).replace('.', '')
                            key = [base_key,
                                    base_dir_name,
                                    rel_dir,
                                    name]
                            key = normpath('/'.join(key))
                            key = key.replace('\\', '/')
                            full_path = join(dirpath, name)
                            s3.upload_file(
                                full_path, Bucket=s3_bucket, Key=key)
                else:
                    key = base_key + '/' + basename(path)
                    s3.upload_file(path, Bucket=s3_bucket, Key=key)
    
    def __generate_session_id(self):
        current_date_time = datetime.utcnow() + timedelta(hours=2, minutes=0)
        return current_date_time.strftime("%Y-%m-%d_%Hh%M")

    def _run_experiment(self, module, s3_bucket, results_path, log_path, experiment_name):
        """
        Executed locally from the instance to run the experiment and shutdown / notify once finished.
        """
        experiment_name = experiment_name if experiment_name else self.__generate_session_id()
        start_time = time.time()
        files_to_upload = [log_path]
        # assert that log path is writable
        try:
            f = open(log_path, 'w')
            f.close()
        except IOError as err:
            self.__notify('log unwritable', experiment_name)
            raise err
        
        # yield experiment execution, logging and catching any errors
        try:
            with open(log_path, 'w') as log:
                with stdout_redirect(log):
                    importlib.import_module(module)
            files_to_upload.append(results_path)
            status = 'completed'
        except:
            status = 'error'
            with open(log_path, 'a') as exceptionlog:
                exceptionlog.write(traceback.format_exc(limit=None))
        finally:
            # when done, notify and shutdown instance (if running for at least 5 mins)
            self.__upload_files(files_to_upload, experiment_name, s3_bucket)

            runtime_in_minutes = round(((time.time() - start_time) / 60), 0)
            self.__notify(status, experiment_name, runtime_in_minutes)
            its_time_to_shut_down = runtime_in_minutes > 5
            if(its_time_to_shut_down):
                try:
                    self.terminate_instance()
                except:
                    self.__notify('not terminated', experiment_name)


# Command Line Interface
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Manage AWS experiments.')
    parser.add_argument('-a', '--action', type=str, nargs='+',
                        help='Which of the available action(s) to perform: create|start|setup|experiment|stop|terminate')
    parser.add_argument('-i', '--instance', type=str,
                        help='ID of an existing AWS instance')
    parser.add_argument('-l', '--launchspec', type=str,
                        help='path to launchSpecfication.json')
    parser.add_argument('-u', '--user', type=str,
                        help='User name used to connect to the instance via SSH (optional, defaults to no user name)')
    parser.add_argument('-n', '--notify', type=str,
                        help='URL to notify on experiment completion')
    parser.add_argument('-d', '--docker', type=str,
                        help='Docker repository to pull from')
    parser.add_argument('-g', '--git', type=str,
                        help='Git repository to pull from')
    parser.add_argument('-b', '--branch', type=str, default='master',
                        help='Git branch to pull from')
    parser.add_argument('-m', '--module', type=str,
                        help='Module to execute on remote server (for run experiment)')
    parser.add_argument('--results-path', type = str,
                        help = 'Directory path (inside docker container) to add to the results file')
    parser.add_argument('-e', '--name', type=str,
                        help='Name of the experiment (S3 key prefix)')
    parser.add_argument('-s', '--bucket', type=str,
                        help='S3 bucket name to upload files to')
    parser.add_argument('--log-path', type=str, default='/var/tmp/experiment.log',
                        help='Path (inside docker container)')
    args = parser.parse_args()
    
    remote_experiment = RemoteExperiment(args)
