import json
import pprint

class Builder():
    def __init__(self, parent, context):
        self.parent = parent
        self.context = context
        self.scope = context['Scope']
        self.subscope = context['Parameters']['Name']
        self.environment = context['Environment'] if 'Environment' in context else {}
        self.environments = context['Environments']
        self.source_repo = context['Parameters']['SourceRepo']

        # Get parameters w/ defaults
        self.include_cf_vars = context['Parameters'].get('IncludeCfVars', True)
        self.manual_approval_postdev = context['Parameters'].get('ManualApprovalPostDev', True)
        self.manual_approval_preprod = context['Parameters'].get('ManualApprovalPreProd', False)
        self.cicd_codebuild = context['Parameters'].get('CicdCodeBuild', False)
        self.cicd_cloudformation = context['Parameters'].get('CicdCloudFormation', False)
        self.sdlc_codebuild = context['Parameters'].get('SdlcCodeBuild', False)
        self.sdlc_cloudformation = context['Parameters'].get('SdlcCloudFormation', True)
        self.sdlc_stack_name = context['Parameters'].get('SdlcStackName', None)
        self.sdlc_ecs = context['Parameters'].get('SdlcEcs', False)
        self.sdlc_ecs_cluster_name = context['Parameters'].get('SdlcEcsClusterName', None)

class CodeCommitBuilder(Builder):

    def __init__(self, parent, context):
        super().__init__(parent, context)
        self.action = {}

    def Build(self):
        source_type = self.source_repo.split(':')[0].lower()
        if source_type != "codecommit":
            return self.parent
        repo_name = self.source_repo.split(':')[1]
        self.action = {
            "ActionTypeId":{
                "Category":"Source",
                "Owner":"AWS",
                "Provider":"CodeCommit",
                "Version":"1"
            },
            "Configuration":{
                "RepositoryName": repo_name,
                "BranchName":"master"
            },
            "Name":"CodeCommit",
            "OutputArtifacts":[
                {
                    "Name":"SourceOutput"
                }
            ],
            "RunOrder": 1,
            "RoleArn": {
                "Fn::Sub":"arn:aws:iam::${AWS::AccountId}:role/cicd-${MainPipeline}-scopes-" + self.scope + "-CodePipelineRole"
            }
        }
        self.parent.actions.extend([self.action])
        return self.parent

class GitHubBuilder(Builder):

    def __init__(self, parent, context):
        super().__init__(parent, context)
        self.action = {}

    def Build(self):
        source_type = self.source_repo.split(':')[0].lower()
        if source_type != "github":
            return self.parent
        repo_owner = self.source_repo.split(':')[1]
        repo_name = self.source_repo.split(':')[2]
        repo_token = self.source_repo.split(':')[3]
        self.action = {
            "ActionTypeId":{
                "Category": "Source",
                "Owner": "ThirdParty",
                "Provider": "GitHub",
                "Version": "1"
            },
            "Configuration":{
                "Branch":"master",
                "Owner": repo_owner,
                "Repo": repo_name,
                "OAuthToken": repo_token,
                "PollForSourceChanges": "True"
            },
            "Name":"GitHub",
            "OutputArtifacts":[
                {
                    "Name":"SourceOutput"
                }
            ],
            "RunOrder": 1,
            "RoleArn": {
                "Fn::Sub":"arn:aws:iam::${AWS::AccountId}:role/cicd-${MainPipeline}-scopes-" + self.scope + "-CodePipelineRole"
            }
        }
        self.parent.actions.extend(self.action)
        return self.parent

class SourceStageBuilder(Builder):

    def __init__(self, parent, context):
        super().__init__(parent, context)
        self.actions = []
        self.stage = {}

    def CodeCommit(self):
        return CodeCommitBuilder(self, self.context)

    def GitHub(self):
        return GitHubBuilder(self, self.context)

    def Build(self):
        self.stage = {
            "Name": "Source",
            "Actions": self.actions
        }
        self.parent.stages.extend([self.stage])
        return self.parent

class CicdCloudFormationBuilder(Builder):

    def __init__(self, parent, context):
        super().__init__(parent, context)
        self.action = {}

    def Build(self):
        if not self.cicd_cloudformation:
            return self.parent
        self.action = {
            "ActionTypeId":{
                "Category":"Deploy",
                "Owner":"AWS",
                "Provider":"CloudFormation",
                "Version":"1"
            },
            "Configuration": {
                "ActionMode":"REPLACE_ON_FAILURE",
                "Capabilities":"CAPABILITY_IAM,CAPABILITY_AUTO_EXPAND",
                "RoleArn":{
                    "Fn::Sub":"arn:aws:iam::" + self.environment['AccountId'] + ":role/" + self.environment['Name'].lower() + "-${MainPipeline}-scopes-" + self.scope + "-CloudFormationRole"
                },
                "StackName":{
                    "Fn::Sub": self.environment['Name'].lower() + "-" + self.scope + "-" + self.subscope
                },
                "TemplatePath": "SourceOutput::CloudFormation-CICD.template",
                "TemplateConfiguration": "SourceOutput::cfvars/" + self.environment['Name'] + ".template" if self.include_cf_vars else { "Ref": "AWS::NoValue" },
                "ParameterOverrides": {
                    "Fn::Join": [
                        "",
                        [
                            "{",
                            "\"PipelineS3BucketName\": { \"Fn::GetArtifactAtt\": [\"SourceOutput\", \"BucketName\"]},",
                            "\"PipelineS3ObjectKey\": { \"Fn::GetArtifactAtt\": [\"SourceOutput\", \"ObjectKey\"]},",
                            {
                                "Fn::Sub": [
                                    "\"PipelineKmsKeyArn\": \"${KmsKeyArn}\",",
                                    {
                                        "KmsKeyArn": {
                                            "Fn::GetAtt": [
                                                "KmsKey",
                                                "Arn"
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                "Fn::Sub": "\"Environment\": \"" + self.environment['Name'].lower() + "\","
                            },
                            {
                                "Fn::Sub": "\"MainPipeline\": \"${MainPipeline}\","
                            },
                            {
                                "Fn::Sub": "\"Scope\": \"" + self.scope + "\","
                            },
                            {
                                "Fn::Sub": "\"SubScope\": \"" + self.subscope + "\""
                            },
                            "}"
                        ]
                    ]
                }
            },
            "Name": "DeployCloudFormation",
            "InputArtifacts": [
                {
                    "Name": "SourceOutput"
                }
            ],
            "RunOrder": 1,
            "RoleArn": {
                "Fn::Sub":"arn:aws:iam::" + self.environment['AccountId'] + ":role/" + self.environment['Name'].lower() + "-${MainPipeline}-scopes-" + self.scope + "-CodePipelineRole"
            }
        }
        self.parent.actions.append(self.action)
        return self.parent

class CicdCodeBuildBuilder(Builder):

    def __init__(self, parent, context):
        super().__init__(parent, context)

    def Build(self):
        if not self.cicd_codebuild:
            return self.parent
        self.action = {
            "ActionTypeId": {
                "Category": "Build",
                "Owner": "AWS",
                "Provider": "CodeBuild",
                "Version": "1"
            },
            "Configuration": {
                "ProjectName": {
                    "Fn::Sub": self.environment['Name'].lower() + "-" + self.scope + "-" + self.subscope + "-CodeBuild"
                }
            },
            "Name": "RunCodeBuild",
            "InputArtifacts": [
                {
                    "Name": "SourceOutput"
                }
            ],
            "RunOrder": 2,
            "OutputArtifacts":[
                {
                    "Name":"BuildOutput"
                }
            ],
            "RoleArn": {
                "Fn::Sub":"arn:aws:iam::" + self.environment['AccountId'] + ":role/" + self.environment['Name'].lower() + "-${MainPipeline}-scopes-" + self.scope + "-CodePipelineRole"
            }
        }
        self.parent.actions.append(self.action)
        return self.parent

class CicdStageBuilder(Builder):

    def __init__(self, parent, context):
        super().__init__(parent, context)
        self.actions = []

    def CicdCloudFormation(self):
        return CicdCloudFormationBuilder(self, self.context)

    def CicdCodeBuild(self):
        return CicdCodeBuildBuilder(self, self.context)

    def Build(self):
        # If not CICD environment, return parent
        if self.context['Environment']['Type'] != 'CICD':
            return self.parent
        # If CodeBuild or CloudFormation not specified, return parent
        if not self.cicd_codebuild and not self.cicd_cloudformation:
            return self.parent
        # Else
        self.parent.actions.extend(self.actions)
        return self.parent

class SdlcCloudFormationBuilder(Builder):
    def __init__(self, parent, context):
        super().__init__(parent, context)

    def Build(self):
        if not self.sdlc_cloudformation:
            return self.parent
        self.parent.actions.append(
            {
                "ActionTypeId":{
                    "Category":"Deploy",
                    "Owner":"AWS",
                    "Provider":"CloudFormation",
                    "Version":"1"
                },
                "Configuration":{
                    "ActionMode":"REPLACE_ON_FAILURE",
                    "Capabilities":"CAPABILITY_IAM,CAPABILITY_AUTO_EXPAND",
                    "RoleArn":{
                        "Fn::Sub":"arn:aws:iam::" + self.environment['AccountId'] + ":role/"+ self.environment['Name'].lower() + "-${MainPipeline}-scopes-" + self.scope + "-CloudFormationRole"
                    },
                    "StackName":  self.environment['Name'].lower() + "-" + self.scope + "-" + self.subscope if not self.sdlc_stack_name else self.sdlc_stack_name.replace('${Environment}', self.environment['Name'].lower()),
                    "TemplatePath": "BuildOutput::CloudFormation-SDLC.template" if self.cicd_codebuild else "SourceOutput::CloudFormation-SDLC.template",
                    "TemplateConfiguration": ( "BuildOutput::cfvars/" + self.environment['Name'] + ".template" if self.cicd_codebuild else "SourceOutput::cfvars/" + self.environment['Name'] + ".template" ) if self.include_cf_vars else { "Ref": "AWS::NoValue" },
                    "ParameterOverrides":{
                        "Fn::Join": [
                            "",
                            [
                                "{",
                                "\"PipelineS3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"BuildOutput\", \"BucketName\"]}, \"PipelineS3ObjectKey\" : { \"Fn::GetArtifactAtt\" : [\"BuildOutput\", \"ObjectKey\"]}," if self.cicd_codebuild else
                                    "\"PipelineS3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"BucketName\"]}, \"PipelineS3ObjectKey\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"ObjectKey\"]},",
                                {
                                    "Fn::Sub": [
                                        "\"PipelineKmsKeyArn\": \"${KmsKeyArn}\",",
                                        {
                                            "KmsKeyArn": {
                                                "Fn::GetAtt": [
                                                    "KmsKey",
                                                    "Arn"
                                                ]
                                            }
                                        }
                                    ]
                                },
                                {
                                    "Fn::Sub": "\"Environment\": \"" + self.environment['Name'].lower() + "\","
                                },
                                {
                                    "Fn::Sub": "\"MainPipeline\": \"${MainPipeline}\","
                                },
                                {
                                    "Fn::Sub": "\"Scope\": \"" + self.scope + "\","
                                },
                                {
                                    "Fn::Sub": "\"SubScope\": \"" + self.subscope + "\""
                                },
                                "}"
                            ]
                        ]
                    }
                },
                "Name": "DeployCloudFormation" ,
                "InputArtifacts": [
                    {
                        "Name": "SourceOutput"
                    },
                    { "Name": "BuildOutput" } if self.cicd_codebuild else { "Ref": "AWS::NoValue" }
                ],
                "RunOrder": 1,
                "RoleArn": {
                    "Fn::Sub":"arn:aws:iam::" + self.environment['AccountId'] + ":role/" + self.environment['Name'].lower() + "-${MainPipeline}-scopes-" + self.scope + "-CodePipelineRole"
                }
            }
        )
        return self.parent

class SdlcCodeBuildBuilder(Builder):
    def __init__(self, parent, context):
        super().__init__(parent, context)

    def Build(self):
        if not self.sdlc_codebuild:
            return self.parent
        self.parent.actions.append(
            {
                "ActionTypeId": {
                    "Category": "Build",
                    "Owner": "AWS",
                    "Provider": "CodeBuild",
                    "Version": "1"
                },
                "Configuration": {
                    "ProjectName": {
                        "Fn::Sub": self.environment['Name'].lower() + "-" + self.scope + "-" + self.subscope + "-CodeBuild"
                    },
                    "PrimarySource": "BuildOutput" if self.cicd_codebuild else "SourceOutput"
                },
                "Name": "RunCodeBuild",
                "InputArtifacts": [
                    {
                        "Name": "SourceOutput"
                    },
                    { "Name": "BuildOutput" } if self.cicd_codebuild else { "Ref": "AWS::NoValue" }
                ],
                "RunOrder": 3,
                "RoleArn": {
                    "Fn::Sub":"arn:aws:iam::" + self.environment['AccountId'] + ":role/" + self.environment['Name'].lower() + "-${MainPipeline}-scopes-" + self.scope + "-CodePipelineRole"
                }
            }
        )
        return self.parent

class SdlcEcsBuilder(Builder):
    def __init__(self, parent, context):
        super().__init__(parent, context)

    def Build(self):
        if not self.sdlc_ecs:
            return self.parent
        self.parent.actions.append(
            {
                "ActionTypeId": {
                    "Category": "Deploy",
                    "Owner": "AWS",
                    "Provider": "ECS",
                    "Version": "1"
                },
                "Configuration": {
                    "ClusterName": self.sdlc_ecs_cluster_name,
                    "ServiceName": self.environment['Name'].lower() + '-' + self.scope + '-' + self.subscope,
                    "FileName": "imagedefinitions.json"
                },
                "Name": "DeployEcs",
                "InputArtifacts": [
                    { "Name": "BuildOutput" } if self.cicd_codebuild else { "Name": "SourceOutput" }
                ],
                "RunOrder": 2,
                "RoleArn": {
                    "Fn::Sub":"arn:aws:iam::" + self.environment['AccountId'] + ":role/" + self.environment['Name'].lower() + "-${MainPipeline}-scopes-" + self.scope + "-CodePipelineRole"
                }
            }
        )
        return self.parent

class SdlcStageBuilder(Builder):
    def __init__(self, parent, context):
        super().__init__(parent, context)
        self.actions = []

    def SdlcCloudFormation(self):
        return SdlcCloudFormationBuilder(self, self.context)

    def SdlcEcs(self):
        return SdlcEcsBuilder(self, self.context)

    def SdlcCodeBuild(self):
        return SdlcCodeBuildBuilder(self, self.context)

    def Build(self):
        # If not SDLC environment, return parent
        if self.context['Environment']['Type'] != 'SDLC':
            return self.parent
        # If CodeBuild or CloudFormation not specified, return parent
        if not self.sdlc_codebuild and not self.sdlc_cloudformation:
            return self.parent
        self.stage = {
            "Name": self.context['Environment']['Name'],
            "Actions": self.actions
        }
        self.parent.actions.extend(self.actions)
        return self.parent

class ManualApproval(Builder):
    def __init__(self, parent, context):
        super().__init__(parent, context)

    def Build(self):
        if not self.manual_approval_postdev or self.environment['Name'].lower() != 'dev':
            return self.parent
        else:
            self.action = {
                "Name":"ManualApproval",
                "ActionTypeId":{
                    "Category":"Approval",
                    "Owner":"AWS",
                    "Version":"1",
                    "Provider":"Manual"
                },
                "RunOrder": 9
            }
            self.parent.actions.append(self.action)
            return self.parent

class StagesBuilder(Builder):

    def __init__(self, parent, context):
        super().__init__(parent, context)
        self.stages = []

    def Source(self):
        return SourceStageBuilder(self, self.context)

    def Environments(self, envs):
        for env in envs:
            self.stages.append(env)
        return self

    def Build(self):
        self.parent.stages.extend(self.stages)
        return self.parent

class PropertiesBuilder(Builder):

    def __init__(self, parent, context):
        super().__init__(parent, context)
        self.stages = []

    def Stages(self):
        return StagesBuilder(self, self.context)

    def Build(self):
        self.parent.properties = {
            "ArtifactStore":{
                "Type":"S3",
                "Location":{
                    "Ref": "S3Bucket"
                },
                "EncryptionKey": {
                    "Id": {
                        "Fn::GetAtt": [
                            "KmsKey",
                            "Arn"
                        ]
                    },
                    "Type":"KMS"
                }
            },
            "RestartExecutionOnUpdate":"false",
            "RoleArn": {
                "Fn::GetAtt": [
                    "IamRoleCodePipeline",
                    "Arn"
                ]
            },
            "Stages": self.stages
        }
        return self.parent

# Pipeline Builder
class PipelineBuilder:

    def __init__(self, scope, environments, parameters):
        self.context = {
            "Environments": environments,
            "Parameters": parameters,
            "Scope": scope
        }
        self.properties = {}

    def Properties(self):
        return PropertiesBuilder(self, self.context)

    def Build(self):
        return {
            "Type": "AWS::CodePipeline::Pipeline",
            "Condition": "NotInitialCreation",
            "Properties": self.properties
        }

# Environment Builder
class EnvironmentBuilder:
    # def __init__(self, parent, context, env):
    #     super().__init__(parent, context)
    #     self.environment = env

    def __init__(self, scope, environments, parameters, environment):
        self.context = {
            "Environments": environments,
            "Environment": environment,
            "Parameters": parameters,
            "Scope": scope
        }
        self.actions = []

    def Cicd(self):
        return CicdStageBuilder(self, self.context)

    def Sdlc(self):
        return SdlcStageBuilder(self, self.context)

    def ManualApproval(self):
        return ManualApproval(self, self.context)

    def Build(self):
        return {
            "Actions": self.actions,
            "Name": self.context['Environment']['Name']
        }

# parameters = {
#     "IncludeCfVars": True,
#     "SourceRepo": "codecommit:Backups-Infra"
# }

# environments = {
#     "Dev": {
#         "AccountId": "561786094244"
#     },
#     "Qa": {
#         "AccountId": "350733826656"
#     },
#     "Prod": {
#         "AccountId": "717010441323"
#     }
# }

# pipeline = (
#     Pipeline('Backup', 'Infra', environments, parameters)
#         .Properties()
#             .Stages()
#                 .Source()
#                     .CodeCommit()
#                     .Build()
#                     .GitHub()
#                     .Build()
#                 .Build()
#                 .Cicd()
#                     .CicdCloudFormation()
#                     .Build()
#                     .CicdCodeBuild()
#                     .Build()
#                 .Build()
#                 .Sdlc()
#                     .Environments()
#                     .Build()
#                     # .ManualApprovalPostDev()
#                     # .Build()
#                     # .ManualApprovalPreProd()
#                     # .Build()
#                 .Build()
#             .Build()
#         .Build()
#     .Build()
# )
# print(json.dumps(pipeline))