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

# Loop through environments
for env in environments:
    env_lower = env.lower()
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