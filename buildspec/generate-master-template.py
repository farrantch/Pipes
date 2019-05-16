import sys
import time
import os
import json
from collections import OrderedDict

# Filenames
file_environments = 'Config-Environments'
file_master = 'Master'

# Open Files
with open(file_environments + '.template') as e_file:
    environments = json.load(e_file, object_pairs_hook=OrderedDict)
with open(file_master + '.template') as m_file:
    master = json.load(m_file)
    
base_statement = [
    {
        "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${AWS::StackName}-CloudFormationRole"
    },
    {
        "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${AWS::StackName}-CodePipelineRole"
    },
    {
        "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${AWS::StackName}-CodeBuildRole"
    }
]
assume_role_statement = {
    "Fn::If": [
        "NotInitialCreation",
        {
            "Sid": "AllowAssumeEnvironmentRoles",
            "Effect": "Allow",
            "Action": "sts:AssumeRole",
            "Resource": []
        },
        {
            "Ref": "AWS::NoValue"
        }
    ]
}
kms_key_statement = {
    "Fn::If": [
        "NotInitialCreation",
        {
            "Sid": "Allow other accounts to use the key.",
            "Effect": "Allow",
            "Principal": {
                "AWS": []
            },
            "Action": [
                "kms:DescribeKey",
                "kms:Encrypt",
                "kms:Decrypt",
                "kms:ReEncrypt",
                "kms:GenerateDataKey"
            ],
            "Resource": "*"
        },
        {
            "Ref": "AWS::NoValue"
        }
    ]
}
s3_bucket_statement = {
    "Fn::If": [
        "NotInitialCreation",
        {
            "Sid": "AccountsAllowedToS3Bucket",
            "Effect": "Allow",
            "Principal": {
                "AWS": []
            },
            "Action": [
                "s3:Get*",
                "s3:Put*",
                "s3:ListBucket"
            ],
            "Resource": [
                {
                    "Fn::Sub": [
                        "${S3BucketArn}/*",
                        {
                            "S3BucketArn": {
                                "Fn::GetAtt": [
                                    "S3Bucket",
                                    "Arn"
                                ]
                            }
                        }
                    ]
                },
                {
                    "Fn::GetAtt": [
                        "S3Bucket",
                        "Arn"
                    ]
                }
            ]
        },
        {
            "Ref": "AWS::NoValue"
        }
    ]
}

for env in environments:
    env_lower = env.lower()
    base_statement.insert(
        {
            "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${AWS::StackName}-CloudFormationRole"
        }
    )
    base_statement.insert(
        {
            "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${AWS::StackName}-CodePipelineRole"
        }
    )
    base_statement.insert(
        {
            "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${AWS::StackName}-CodeBuildRole"
        }
    )

assume_role_statement['Fn::If'][1]['Resource'] = base_statement
kms_key_statement['Fn::If'][1]['Principal']['AWS'] = base_statement
s3_bucket_statement['Fn::If'][1]['Principal']['AWS'] = base_statement
s3_bucket_statement['Fn::If'][1]['Principal']['AWS'].insert(
    {
        "Fn::GetAtt": [
            "RoleCodePipeline",
            "Arn"
        ]
    }
)

master['Resources']['IamPolicyBaseline']['Properties']['PolicyDocument']['Statement'].insert(assume_role_statement)
master['Resources']['KmsKey']['Properties']['KeyPolicy']['Statement'].insert(kms_key_statement)
master['Resources']['S3BucketPolicy']['Properties']['PolicyDocument']['Statement'].insert(s3_bucket_statement)

# Loop through environments
for key, value in environments.items():
    env = key
    env_lower = env.lower()
    
    # Add SDLC account to master parameters
    master['Parameters'][env + 'Account'] = {
        "Type": "Number",
        "Default": value['AccountId']
    }
    
    # Add SDLC account to master pipeline
    master['Resources']['CodePipeline']['Properties']['Stages'].insert(-1,
        {
            "Name": env,
            "Actions": [
                {
                    "ActionTypeId": {
                        "Category": "Deploy",
                        "Owner": "AWS",
                        "Provider": "CloudFormation",
                        "Version": "1"
                    },
                    "Configuration": {
                        "ActionMode": "CREATE_UPDATE",
                        "Capabilities": "CAPABILITY_NAMED_IAM,CAPABILITY_AUTO_EXPAND",
                        "RoleArn": {
                            "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${AWS::StackName}-CloudFormationRole"
                        },
                        "StackName": {
                            "Fn::Sub": env_lower + "-${AWS::StackName}-infra"
                        },
                        "TemplatePath": "SDLCTemplates::Scope-SDLC-Parent.template",
                        "TemplateConfiguration": "SourceOutput::cfvars/" + env + ".template",
                        "ParameterOverrides": {
                            "Fn::Sub": "{ \"S3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"BucketName\"]}, \"CicdAccount\" : \"${AWS::AccountId}\", \"MasterPipeline\" : \"${AWS::StackName}\"}"
                        }
                    },
                    "Name": "DeployCloudFormation" + env,
                    "InputArtifacts": [
                        {
                            "Name": "SourceOutput"
                        },
                        {
                            "Name": "SDLCTemplates"
                        }
                    ],
                    "RunOrder": 1,
                    "RoleArn": {
                        "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${AWS::StackName}-CodePipelineRole"
                    }
                }
            ]
        }
    )
        
# Save files
with open('generated-master-template/' + file_master + '.template', 'w') as master_file_output:
    json.dump(master, master_file_output, indent=4)