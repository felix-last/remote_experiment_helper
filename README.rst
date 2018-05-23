Remote Experiment Helper
========================

A framework to aid in running experiments inside docker containers on
AWS(ish) instances.

EC2 Instance Prerequisites
--------------------------

EC2 instances used with this module (or AMIs if using the module to
create instances) are expected to have the following software installed.

-  AWS CLI
-  nvidia-docker

The instance should also be set up with an AIM or similar role granting
rights to

-  clone code from your project’s git repository
-  pull images from you project’s docker repository
-  stop / terminate EC2 instances (for self shutdown after experiment)
-  upload data to your S3 bucket

Usage
-----

Add this package to your project’s requirements, then call ``remote.py``
from the command line, passing options depending on the actions to
perform.

.. code:: bash

        python -m remote
            --action        # Which of the available action(s) to perform: create|start|setup|experiment|stop|terminate
            --instance      # ID of an existing AWS instance
            --launchspec    # path to launchSpecfication.json
            --user          # User name used to connect to the instance via SSH (optional, defaults to no user name)
            --notify        # URL to notify on experiment completion
            --docker        # Docker repository to pull from
            --git           # Git repository to pull from
            --module        # Module to execute on remote server (for run experiment)
            --results-path  # Directory path (inside docker container) to add to the results file
            --bucket        # S3 bucket name to upload files to
            --log-path      # Path (inside docker container) to log to (default: /var/tmp/experiment.log)
            --branch        # Git branch to pull from (default: master)
            --name          # Name of the experiment (used as S3 key prefix) (default: completion time in format 'YYYY-MM-DD HHhMM')

Launch Specification
--------------------

Follow these instructions to create the file
``launchSpecification.json``, which is required to create instances on
AWS.

1. Create a launch specification from an existing spot request using AWS
   CLI:

.. code:: bash

    aws ec2 describe-spot-instance-requests --spot-instance-request-ids sir-12345

2. Copy the contents of the attribute ``LaunchSpecification`` into file
   ``launchSpecification.json``.
3. Make sure to remove ``SecurityGroups``. Instead, add attribute
   ``SecurityGroupIds`` containing value of ``GroupId``.

Sample of ``launchSpecification.json``:

.. code:: json

    {
        "Placement": {
            "AvailabilityZone": "eu-west-1a"
        },
        "ImageId": "ami-12345",
        "KeyName": "mykey@example",
        "BlockDeviceMappings": [
            {
                "DeviceName": "/dev/xvda",
                "Ebs": {
                    "DeleteOnTermination": true,
                    "VolumeType": "gp2",
                    "VolumeSize": 80
                }
            }
        ],
        "EbsOptimized": false,
        "SecurityGroupIds": [
            "sg-12345"
        ],
        "SubnetId": "subnet-12345",
        "Monitoring": {
            "Enabled": false
        },
        "IamInstanceProfile": {
            "Arn": "arn:aws:iam::12345:instance-profile/some-iam"
        },
        "InstanceType": "p2.xlarge"
    }
