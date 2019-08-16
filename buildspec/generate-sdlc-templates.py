import boto3
import sys
import time
import os
import json

# Filenames
file_scopes = 'config/Scopes'
file_sdlc_parent = 'Scope-SDLC-Parent'
file_sdlc_child = 'Scope-SDLC-Child'

# Open Files
# Input Files
with open(file_scopes + '.template') as s_file:
    scopes = json.load(s_file)
with open('scope-templates/' + file_sdlc_parent + '.template') as sp_file:
    sdlc_parent = json.load(sp_file)
    
client = boto3.client('cloudformation')

#MASTERSCOPESTACK = os.environ['MASTERSCOPESTACK']
#ENVIRONMENT = os.environ['Environment']

MASTERSCOPESTACK = 'cicd-master-scopes'
# ENVIRONMENT = 'cicd'

# Get master infra stack resources
resource_summaries = client.list_stack_resources(
    StackName=MASTERSCOPESTACK
)['StackResourceSummaries']

# Get cicd child stack outputs
child_stack_outputs = {}
# Loop through master infra stack resources
for rs in resource_summaries:
    # Only look for CloudFormation Stacks
    if rs['ResourceType'] == 'AWS::CloudFormation::Stack':
        # Get Stack outputs
        child_stack_outputs[rs['LogicalResourceId']] = client.describe_stacks(
            StackName = rs['PhysicalResourceId']
        )['Stacks'][0]['Outputs']

# Loop through infra scopes within pipeline file
for key, value in scopes.items():
    scope = key.lower()
    
    # Determine stack output values
    s3_bucket_name = list(filter(lambda item: item['OutputKey'] == 'S3BucketName', child_stack_outputs[scope]))[0]['OutputValue']
    kms_cmk_arn = list(filter(lambda item: item['OutputKey'] == 'KmsCmkArn', child_stack_outputs[scope]))[0]['OutputValue']
    
    sdlc_parent['Resources'][scope] = {
          "Type" : "AWS::CloudFormation::Stack",
          "Properties": {
            "Parameters": {
                "S3BucketName": s3_bucket_name,
                "CicdAccount": {
                    "Ref": "CicdAccount"
                },
                "KmsCmkArn": kms_cmk_arn,
                "MasterPipeline": {
                    "Ref": "MasterPipeline"
                },
                "Environment": {
                    "Ref": "Environment"
                },
                "Scope": scope,
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
                "Fn::Sub": "https://s3.amazonaws.com/${S3BucketName}/generated-sdlc-templates/Scope-SDLC-Child-" + scope + ".template"
            }
        }
    }
    
    # Open child template to insert CodeBuildProjects
    with open('scope-templates/' + file_sdlc_child + '.template') as sc_file:
        sdlc_child = json.load(sc_file)
        
    # # Loop through pipelines
    # if 'Pipelines' in value:
    #     for pipeline in value['Pipelines']:
    #         name = pipeline['Name'].lower()
    #         # Insert Scope CICD CodeBuildPre Projects
    #         sdlc_child['Resources'][pipeline['Name']] = {
    #             "Type": "AWS::CloudFormation::Stack",
    #             "Properties": {
    #                 "Parameters": {
    #                     "Scope": scope,
    #                     "SubScope": name,
    #                     "Environment": {
    #                         "Ref": "Environment"
    #                     },
    #                     "KmsCmkArn": {
    #                         "Ref": "KmsCmkArn"
    #                     },
    #                     "RoleArnCodeBuild": {
    #                         "Fn::GetAtt": [
    #                             "IamRoleCodeBuild",
    #                             "Arn"
    #                         ]
    #                     },
    #                     "MasterPipeline": {
    #                         "Ref": "MasterPipeline"
    #                     }
    #                 },
    #                 "Tags": [
    #                     {
    #                         "Key": "Environment",
    #                         "Value": {
    #                             "Fn::Sub": "${Environment}"
    #                         }
    #                     }
    #                 ],
    #                 "TemplateURL": {
    #                     "Fn::Sub": "https://s3.amazonaws.com/${MasterS3BucketName}/infra-templates/SDLC.template"
    #                 }
    #             }
    #         }
            
    #         # Add Parameter Overrides
    #         if 'Parameters' in pipeline:
    #             for po, po_value in pipeline['Parameters'].items():
    #                 # Filter to parameters only applicable to SDLC stack
    #                 if po == 'SdlcCodeBuildPre' or po == 'SdlcCodeBuildPost' or po == 'SdlcCodeBuildImagePre' or po == 'SdlcCodeBuildImagePost':
    #                     sdlc_child['Resources'][pipeline['Name']]['Properties']['Parameters'][po] = po_value
        
    # Add policy statements to PolicyBaseline
    # First, add resource-scoped/* if exists
    if 'resource-scoped/*' in value['Policies']:
        for filename in os.listdir('policies/resource-scoped'):
            with open('policies/resource-scoped/' + filename) as f:
                d = json.load(f)
            for s in d['Statements']:
                sdlc_child['Resources']['IamPolicyBaseline']['Properties']['PolicyDocument']['Statement'].append(s)
    # Add rest of policies
    for ps in value['Policies']:
        if ps != 'resource-scoped/*':
            with open('policies/' + str(ps) + '.template') as json_file:
                data = json.load(json_file)
            # Don't re-add resource-scope policies if already added via wildcard
            if not ps.startswith('resource-scoped/') and 'resource-scoped/*' in value['Policies']:
                for statement in data['Statements']:
                    sdlc_child['Resources']['IamPolicyBaseline']['Properties']['PolicyDocument']['Statement'].append(statement)
    
    with open('generated-sdlc-templates/' + file_sdlc_child + '-' + scope + '.template', 'w') as sc_file_output:
        json.dump(sdlc_child, sc_file_output, indent=4)
    
# Save files
with open('generated-sdlc-templates/' + file_sdlc_parent + '.template', 'w') as sp_file_output:
    json.dump(sdlc_parent, sp_file_output, indent=4)