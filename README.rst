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

Launch Specification
--------------------

Follow these instructions to create the file
``remote/launchSpecification.json``, which is required to create
instances on AWS.

1. Create a launch specification from an existing spot request using AWS
   CLI:

.. code:: bash

    aws ec2 describe-spot-instance-requests --spot-instance-request-ids sir-12345

2. Copy the contents of the attribute ``LaunchSpecification`` into file
   ``remote/launchSpecification.json``.
3. Make sure to remove ``SecurityGroups``. Instead, add attribute
   ``SecurityGroupIds`` containing value of ``GroupId``.

Sample of ``remote/launchSpecification.json``:

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
