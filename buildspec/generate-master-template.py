import sys
import time
import os
import json
from collections import OrderedDict

# Filenames
file_environments = 'Config-Environments'
file_users = 'Config-Users'
file_master = 'Master'

# Open Files
with open(file_environments + '.template') as e_file:
    environments = json.load(e_file, object_pairs_hook=OrderedDict)
with open(file_master + '.template') as m_file:
    master = json.load(m_file)
with open(file_users + '.template') as users_file:
    users = json.load(users_file)
    
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

for env in environments['SdlcAccounts']:
    env_lower = env.lower()
    base_statement.append(
        {
            "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${AWS::StackName}-CloudFormationRole"
        }
    )
    base_statement.append(
        {
            "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${AWS::StackName}-CodePipelineRole"
        }
    )
    base_statement.append(
        {
            "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${AWS::StackName}-CodeBuildRole"
        }
    )

assume_role_statement['Fn::If'][1]['Resource'] = base_statement
kms_key_statement['Fn::If'][1]['Principal']['AWS'] = base_statement
s3_bucket_statement['Fn::If'][1]['Principal']['AWS'] = base_statement
s3_bucket_statement['Fn::If'][1]['Principal']['AWS'].append(
    {
        "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/${AWS::StackName}-CodePipelineRole"
    }
)

master['Resources']['IamPolicyBaseline']['Properties']['PolicyDocument']['Statement'].append(assume_role_statement)
master['Resources']['KmsKey']['Properties']['KeyPolicy']['Statement'].append(kms_key_statement)
master['Resources']['S3BucketPolicy']['Properties']['PolicyDocument']['Statement'].append(s3_bucket_statement)

# Add CICD Users stack
if users:
    master['Resources']['CodePipeline']['Properties']['Stages'][2]['Actions'].append(
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
                    "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${AWS::StackName}-CloudFormationRole"
                },
                "StackName": {
                    "Fn::Sub": "cicd-${AWS::StackName}-users"
                },
                "TemplatePath": "CicdTemplates::Users.template",
                "TemplateConfiguration": "SourceOutput::cfvars/Cicd.template",
                "ParameterOverrides": {
                    "Fn::Sub": "{ \"S3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"BucketName\"]}, \"MasterPipeline\" : \"${AWS::StackName}\"}"  
                }
            },
            "Name": "DeployCicdUsers",
            "InputArtifacts": [
                {
                    "Name": "SourceOutput"
                },
                {
                    "Name": "CicdTemplates"
                }
            ],
            "RunOrder": 2,
            "RoleArn": {
                "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${AWS::StackName}-CodePipelineRole"
            }
        }
    )

run_order = 2
# Loop through environments
for key, value in environments['SdlcAccounts'].items():
    env = key
    env_lower = env.lower()
    
    # Add SDLC account to master parameters
    master['Parameters'][env + 'Account'] = {
        "Type": "Number",
        "Default": value['AccountId']
    }
    
    # Add SDLC account to master pipeline
    master['Resources']['CodePipeline']['Properties']['Stages'][-2]['Actions'].append(
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
                    "Fn::Sub": env_lower + "-${AWS::StackName}-scopes"
                },
                "TemplatePath": "SdlcTemplates::Scope-SDLC-Parent.template",
                "TemplateConfiguration": "SourceOutput::cfvars/" + env + ".template",
                "ParameterOverrides": {
                    "Fn::Sub": "{ \"S3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"BucketName\"]}, \"CicdAccount\" : \"${AWS::AccountId}\", \"MasterPipeline\" : \"${AWS::StackName}\"}"
                }
            },
            "Name": "Deploy" + env + "Scopes",
            "InputArtifacts": [
                {
                    "Name": "SourceOutput"
                },
                {
                    "Name": "SdlcTemplates"
                }
            ],
            "RunOrder": run_order,
            "RoleArn": {
                "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${AWS::StackName}-CodePipelineRole"
            }
        }
    )
    if users:
        master['Resources']['CodePipeline']['Properties']['Stages'][-2]['Actions'].append(
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
                        "Fn::Sub": env_lower + "-${AWS::StackName}-users"
                    },
                    "TemplatePath": "SdlcTemplates::Users.template",
                    "TemplateConfiguration": "SourceOutput::cfvars/" + env + ".template",
                    "ParameterOverrides": {
                        "Fn::Sub": "{ \"S3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"BucketName\"]}, \"MasterPipeline\" : \"${AWS::StackName}\"}"
                    }
                },
                "Name": "Deploy" + env + "Users",
                "InputArtifacts": [
                    {
                        "Name": "SourceOutput"
                    },
                    {
                        "Name": "SdlcTemplates"
                    }
                ],
                "RunOrder": run_order,
                "RoleArn": {
                    "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${AWS::StackName}-CodePipelineRole"
                }
            }
        )
    if run_order == 2:
        run_order = run_order + 1
    run_order = run_order + 1
        
# Save files
with open('generated-master-template/' + file_master + '.template', 'w') as master_file_output:
    json.dump(master, master_file_output, indent=4)