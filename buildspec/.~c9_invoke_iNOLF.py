import boto3
import sys
import time
import os
import json

# Filenames
file_pipelines = 'Pipelines.json'
file_sdlc_parent = 'Scope-SDLC-Parent'
file_sdlc_child = 'Scope-SDLC-Child'

# Open Files
# Input Files
with open(file_pipelines) as pl_file:
    pipelines = json.load(pl_file)
with open(file_sdlc_parent + '.template') as sp_file:
    sdlc_parent = json.load(sp_file)
    
    
with open(file_sdlc_child + '.template') as sc_file:
    sdlc_child = json.load(sc_file)
    
client = boto3.client('cloudformation')

#MASTERINFRASTACK = os.environ['MasterInfraStack']
#ENVIRONMENT = os.environ['Environment']

MASTERINFRASTACK = 'cicd-master-infra'
# ENVIRONMENT = 'cicd'

# Get master infra stack resources
resource_summaries = client.list_stack_resources(
    StackName=MASTERINFRASTACK
)['StackResourceSummaries']

# Get cicd child stack outputs
child_stack_outputs = {}
# Loop through master infra stack resources
for rs in resource_summaries:
    # Only look for CloudFormation Stacks
    if rs['ResourceType'] == 'AWS::CloudFormation::Stack':
        # Get Stack outputs
        child_stack_parameters[rs['LogicalResourceId']] = client.describe_stacks(
            StackName = rs['PhysicalResourceId']
        )['Stacks'][0]['Outputs']

# Loop through infra scopes within pipeline file
for key, value in pipelines.items():
    scope = key.lower()
    
    # Determine AllEnvironmentsCreated value
    
    sdlc_parent['Resources'][scope] = {
          "Type" : "AWS::CloudFormation::Stack",
          "Properties": {
            "Parameters": {
                "S3BucketName": {},
                "CicdAccount": {
                    "Ref": "CicdAccount"
                },
                "KmsCmkArn": {},
                "MasterPipeline": {
                    "Ref": "MasterPipeline"
                },
                "Environment": {
                    "Ref": "Environment"
                },
                "Scope": "network",
                "MasterS3BucketName": {
                    "Fn::Sub": "${S3BucketName}"
                }
            },
            "Tags" : [
                {
                    "Key": "Environment",
                    "Value": {
                        "Fn::Sub": "${Environment}"
                    }
                }
            ],
            "TemplateURL" : {
                "Fn::Sub": "https://s3.amazonaws.com/${S3BucketName}/generated-sdlc-templates/Scope-SDLC-Child.template"
            }
        }
    }
    
    # Insert Scope CICD Stacks
    # cicd_parent['Resources']['Pipeline' + key] = {
    #     "Type": "AWS::CloudFormation::Stack",
    #     "Condition": "NotInitialCreation",
    #     "Properties": {
    #         "Parameters": {
    #             "DevAccount": {
    #                 "Ref": "DevAccount"
    #             },
    #             "ProdAccount": {
    #                 "Ref": "ProdAccount"
    #             },
    #             "MasterPipeline": {
    #                 "Ref": "MasterPipeline"
    #             },
    #             "Environment": {
    #                 "Ref": "Environment"
    #             },
    #             "Scope": {
    #                 "Fn::Sub": "${Scope}"
    #             },
    #             "AllEnvironmentsCreated": "False"
    #         },
    #         "Tags": [{
    #             "Key": "Environment",
    #             "Value": {
    #                 "Fn::Sub": "${Environment}"
    #             }
    #         }],
    #         "TemplateURL": {
    #             "Fn::Sub": "https://s3.amazonaws.com/${S3BucketName}/generated-stacks/${Scope}.template"
    #         }
    #     }
    # }
    
# Save files
with open('generated-sdlc-templates/' + file_sdlc_parent + '.template', 'w') as sp_file_output:
    json.dump(sdlc_parent, sp_file_output, indent=4)
with open('generated-sdlc-templates/' + file_sdlc_child + '.template', 'w') as sc_file_output:
    json.dump(sdlc_child, sc_file_output, indent=4)