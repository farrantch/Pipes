import sys
import time
import os
import json
from collections import OrderedDict
from utils import *

environments = read_file(FILE_CONFIG_ENVIRONMENTS)
main = read_file(FILE_TEMPLATE_MAIN)
users = read_file(FILE_CONFIG_USERS)
kmskeys = read_file(FILE_CONFIG_KEYS)
    
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

main['Resources']['IamPolicyBaseline']['Properties']['PolicyDocument']['Statement'].append(assume_role_statement)
main['Resources']['KmsKey']['Properties']['KeyPolicy']['Statement'].append(kms_key_statement)
main['Resources']['S3BucketPolicy']['Properties']['PolicyDocument']['Statement'].append(s3_bucket_statement)

# Add CICD Keys Stack if cicd environment keys specified
if any('Cicd' in value and value['Cicd'] == True for (key, value) in kmskeys.items()):
    main['Resources']['CodePipeline']['Properties']['Stages'][3]['Actions'].append(
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
                    "Fn::Sub": "cicd-${AWS::StackName}-keys"
                },
                "TemplatePath": "EnvironmentTemplates::generated-key-templates-cicd/Keys-Parent.template",
                "TemplateConfiguration": "SourceOutput::cfvars/Cicd.template",
                "ParameterOverrides": {
                    "Fn::Sub": "{ \"S3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"BucketName\"]}, \"MainPipeline\" : \"${AWS::StackName}\"}"  
                }
            },
            "Name": "DeployCicdKeys",
            "InputArtifacts": [
                {
                    "Name": "SourceOutput"
                },
                {
                    "Name": "EnvironmentTemplates"
                }
            ],
            "RunOrder": 2,
            "RoleArn": {
                "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${AWS::StackName}-CodePipelineRole"
            }
        }
    )

# Add CICD Users stack
if users:
    main['Resources']['CodePipeline']['Properties']['Stages'][3]['Actions'].append(
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
                "TemplatePath": "EnvironmentTemplates::generated-user-templates-cicd/Users-Parent.template",
                "TemplateConfiguration": "SourceOutput::cfvars/Cicd.template",
                "ParameterOverrides": {
                    "Fn::Sub": "{ \"S3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"BucketName\"]}, \"MainPipeline\" : \"${AWS::StackName}\"}"  
                }
            },
            "Name": "DeployCicdUsers",
            "InputArtifacts": [
                {
                    "Name": "SourceOutput"
                },
                {
                    "Name": "EnvironmentTemplates"
                }
            ],
            "RunOrder": 3,
            "RoleArn": {
                "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${AWS::StackName}-CodePipelineRole"
            }
        }
    )


run_order = 4
# Loop through environments
for key, value in environments['SdlcAccounts'].items():
    env = key
    env_lower = env.lower()
    
    # Add SDLC account to main parameters
    main['Parameters'][env + 'Account'] = {
        "Type": "Number",
        "Default": value['AccountId']
    }

    # Add SDLC Keys Stack if cicd environment keys specified
    if any('Sdlc' in value and value['Sdlc'] == True for (key, value) in kmskeys.items()):
        main['Resources']['CodePipeline']['Properties']['Stages'][-2]['Actions'].append(
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
                        "Fn::Sub": env_lower + "-${AWS::StackName}-keys"
                    },
                    "TemplatePath": "EnvironmentTemplates::generated-key-templates-sdlc/Keys-Parent.template",
                    "TemplateConfiguration": "SourceOutput::cfvars/" + env + ".template",
                    "ParameterOverrides": {
                        "Fn::Sub": "{ \"S3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"BucketName\"]}, \"MainPipeline\" : \"${AWS::StackName}\"}"
                    }
                },
                "Name": "Deploy" + env + "Keys",
                "InputArtifacts": [
                    {
                        "Name": "SourceOutput"
                    },
                    {
                        "Name": "EnvironmentTemplates"
                    }
                ],
                "RunOrder": run_order,
                "RoleArn": {
                    "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${AWS::StackName}-CodePipelineRole"
                }
            }
        )
        run_order += 1

    # Add SDLC account to main pipeline
    main['Resources']['CodePipeline']['Properties']['Stages'][-2]['Actions'].append(
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
                "TemplatePath": "EnvironmentTemplates::generated-scope-templates-sdlc/Scopes-Parent.template",
                "TemplateConfiguration": "SourceOutput::cfvars/" + env + ".template",
                "ParameterOverrides": {
                    "Fn::Sub": "{ \"S3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"BucketName\"]}, \"CicdAccount\" : \"${AWS::AccountId}\", \"MainPipeline\" : \"${AWS::StackName}\"}"
                }
            },
            "Name": "Deploy" + env + "Scopes",
            "InputArtifacts": [
                {
                    "Name": "SourceOutput"
                },
                {
                    "Name": "EnvironmentTemplates"
                }
            ],
            "RunOrder": run_order,
            "RoleArn": {
                "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${AWS::StackName}-CodePipelineRole"
            }
        }
    )
    if users:
        main['Resources']['CodePipeline']['Properties']['Stages'][-2]['Actions'].append(
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
                    "TemplatePath": "EnvironmentTemplates::generated-user-templates-sdlc/Users-Parent.template",
                    "TemplateConfiguration": "SourceOutput::cfvars/" + env + ".template",
                    "ParameterOverrides": {
                        "Fn::Sub": "{ \"S3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"BucketName\"]}, \"MainPipeline\" : \"${AWS::StackName}\"}"
                    }
                },
                "Name": "Deploy" + env + "Users",
                "InputArtifacts": [
                    {
                        "Name": "SourceOutput"
                    },
                    {
                        "Name": "EnvironmentTemplates"
                    }
                ],
                "RunOrder": run_order,
                "RoleArn": {
                    "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${AWS::StackName}-CodePipelineRole"
                }
            }
        )
    # If first run through, skip manual approval dev step
    if run_order == 4 or run_order == 5:
        run_order = run_order + 1
    run_order = run_order + 1
        
# Save files
write_file('generated-main-template/' + FILE_TEMPLATE_MAIN, main)