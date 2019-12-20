import boto3
import sys
import time
import os
import json
import urllib.parse
import generate_user_templates
from argparse import ArgumentParser
from utils import *

def get_cicd_stack_outputs():
    cf_client = boto3.client('cloudformation')
    # Get main infra stack resources
    resource_summaries = cf_client.list_stack_resources(
        StackName=MAIN_PIPELINE_STACK
    )['StackResourceSummaries']

    # Get cicd child stack outputs
    child_stack_outputs = {}
    # Loop through main infra stack resources
    for rs in resource_summaries:
        # Only look for CloudFormation Stacks
        if rs['ResourceType'] == 'AWS::CloudFormation::Stack':
            # Get Stack outputs
            child_stack_outputs[rs['LogicalResourceId']] = cf_client.describe_stacks(
                StackName = rs['PhysicalResourceId']
            )['Stacks'][0]['Outputs']
    return child_stack_outputs

def generate_child_template(template, kmskey, value, environment):
        if environment['Type'] in value and value[environment['Type']] == True:
            template['Resources']['KmsKey' + kmskey] = {
                "Type" : "AWS::KMS::Key",
                "Properties" : {
                    "KeyPolicy": {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {
                                    "AWS": { "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:root" }
                                },
                                "Action": [
                                    "kms:*"
                                ],
                                "Resource": "*"
                            }
                        ]
                    }
                }
            }
            template['Resources']['KmsAlias' + kmskey] = {
                "Type" : "AWS::KMS::Alias",
                "Properties" : {
                    "AliasName" : {
                        "Fn::Sub": "alias/${AWS::StackName}"
                    },
                    "TargetKeyId" : {
                        "Ref": 'KmsKey' + kmskey        
                    }
                }
            }
            template['Outputs']['KmsKeyArn'] = {
                "Value": {
                    "Fn::GetAtt": [
                        "KmsKey" + kmskey,
                        "Arn"
                    ]
                },
                "Export": {
                    "Name": {
                        "Fn::Sub": "${Environment}-${MainPipeline}-keys-${Scope}-KmsKeyArn"
                    }
                }
            }
        return template

def generate_key_templates(environment):
    # Open Files
    kmskeys = read_file(FILE_CONFIG_KEYS)
    key_parent = read_file('templates/' + FILE_TEMPLATE_KEYS_PARENT)

    # Loop through keys
    for key, value in kmskeys.items():
        kmskey = key
        
        key_parent['Resources'][kmskey] = {
            "Type" : "AWS::CloudFormation::Stack",
            "Properties": {
                "Parameters": {
                    "MainPipeline": {
                        "Ref": "MainPipeline"
                    },
                    "Environment": {
                        "Ref": "Environment"
                    },
                    "Scope": kmskey
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
                    "Fn::Sub": "https://s3.amazonaws.com/${S3BucketName}/builds/keys/" + BUILD_NUM + "/" + environment['Name'] + "/Keys-Child-" + kmskey + ".template"
                }
            }
        }
        
        # Open child template to insert KMS Keys
        key_child = read_file('templates/' + FILE_TEMPLATE_KEYS_CHILD)
            
        key_child = generate_child_template(key_child, kmskey, value, environment)

        # Save child file
        write_file(OUTPUT_FOLDER + '/keys/' + environment['Name'] + '/' + FILE_TEMPLATE_KEYS_CHILD + '-' + kmskey, key_child)

    # Save parent file
    write_file(OUTPUT_FOLDER + '/keys/' + environment['Name'] + '/' + FILE_TEMPLATE_KEYS_PARENT, key_parent)

def main():
    # Loop through workload environments
    environments = read_file(FILE_CONFIG_ENVIRONMENTS)
    for env in environments['WorkloadAccounts']:
        # Generate key templates
        generate_key_templates(env)

if __name__ == "__main__":
    main()