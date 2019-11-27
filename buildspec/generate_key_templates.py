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

def generate_child_template(template, kmskey, value, environment_type):
        if environment_type in value:
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

def generate_key_templates(environment_type):
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
                    "Fn::Sub": "https://s3.amazonaws.com/${S3BucketName}/generated-key-templates-" + environment_type.lower() + "/Keys-Child-" + kmskey + ".template"
                }
            }
        }
        
        # Open child template to insert KMS Keys
        key_child = read_file('templates/' + FILE_TEMPLATE_KEYS_CHILD)
            
        key_child = generate_child_template(key_child, kmskey, value, environment_type)

        # Save child file
        write_file('generated-key-templates-' + environment_type.lower() + '/' + FILE_TEMPLATE_KEYS_CHILD + '-' + kmskey, key_child)

    # Save parent file
    write_file('generated-key-templates-' + environment_type.lower() + '/' + FILE_TEMPLATE_KEYS_PARENT, key_parent)

def main():
    # Parse arguments
    parser = ArgumentParser()
    parser.add_argument("-et", "--environment_type", help="Choose environment type. Ex - 'Sdlc' or 'Cicd'")
    args = parser.parse_args()

    # Get outputs from cicd child stacks
    #child_stack_outputs = get_cicd_stack_outputs()

    # Generate scope templates with CICD child stack outputs
    generate_key_templates(args.environment_type)

if __name__ == "__main__":
    main()