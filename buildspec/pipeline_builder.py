import json
import pprint

class Builder():
    def __init__(self, parent, context):
        self.parent = parent
        self.context = context
        self.scope = context['Scope']
        self.scope_lower = context['Scope'].lower()
        self.environments = context['Environments']
        self.name = context['Parameters']['Name']
        self.name_lower = context['Parameters']['Name'].lower()
        self.source_repo = context['Parameters']['SourceRepo']

        # Get parameters w/ defaults
        self.include_cf_vars = context['Parameters'].get('IncludeCfVars', False)
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
            "RunOrder": 1
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
            "RunOrder": 1
        }
        self.parent.actions.extend([self.action])
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
                    "Fn::Sub":"arn:aws:iam::${AWS::AccountId}:role/cicd-${MasterPipeline}-scopes-" + self.scope_lower + "-CloudFormationRole"
                },
                "StackName":{
                    "Fn::Sub": "cicd-" + self.scope_lower + "-" + self.name_lower
                },
                "TemplatePath": "SourceOutput::CloudFormation-CICD.template",
                "TemplateConfiguration": "SourceOutput::cfvars/Cicd.template" if self.include_cf_vars else { "Ref": "AWS::NoValue" },
                "ParameterOverrides": {
                    "Fn::Join": [
                        "",
                        [
                            "{",
                            "\"S3BucketName\": { \"Fn::GetArtifactAtt\": [\"SourceOutput\", \"BucketName\"]},",
                            "\"S3ObjectKey\": { \"Fn::GetArtifactAtt\": [\"SourceOutput\", \"ObjectKey\"]},",
                            {
                                "Fn::Sub": [
                                    "\"KmsCmkArn\": \"${KmsCmkArn}\",",
                                    {
                                        "KmsCmkArn": {
                                            "Fn::GetAtt": [
                                                "KmsKey",
                                                "Arn"
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                "Fn::Sub": "\"Environment\": \"cicd\","
                            },
                            {
                                "Fn::Sub": "\"MasterPipeline\": \"${MasterPipeline}\","
                            },
                            {
                                "Fn::Sub": "\"Scope\": \"" + self.scope_lower + "\","
                            },
                            {
                                "Fn::Sub": "\"SubScope\": \"" + self.name_lower + "\""
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
                "Fn::Sub":"arn:aws:iam::${AWS::AccountId}:role/cicd-${MasterPipeline}-scopes-" + self.scope_lower + "-CodePipelineRole"
            }
        }
        self.parent.actions.extend([self.action])
        return self.parent

class CicdCodeBuildBuilder(Builder):

    def __init__(self, parent, context):
        super().__init__(parent, context)
        self.action = {}

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
                    "Fn::Sub": "cicd-" + self.scope_lower + "-" + self.name_lower + "-CodeBuild"
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
            ]
        }
        self.parent.actions.extend([self.action])
        return self.parent

class CicdStageBuilder(Builder):

    def __init__(self, parent, context):
        super().__init__(parent, context)
        self.actions = []
        self.stage = {}

    def CicdCloudFormation(self):
        return CicdCloudFormationBuilder(self, self.context)

    def CicdCodeBuild(self):
        return CicdCodeBuildBuilder(self, self.context)

    def Build(self):
        if not self.cicd_codebuild and not self.cicd_cloudformation:
            return self.parent
        self.stage = {
            "Name": "Cicd",
            "Actions": self.actions
        }
        self.parent.stages.extend([self.stage])
        return self.parent


    # Foo(['dev','prod'])
    #     self.env = aflkasjf

    # Build()
    #     for env in self.env:
    #         self.parent.foolist
    #     return self.parent

class ManualApprovalPostDev(Builder):

    def __init__(self, parent, context):
        super().__init__(parent, context)
        self.action = {}
    
    def Build(self):
        if not self.manual_approval_postdev:
            return self.parent
        else:
            self.action = {
                "Name":"ManualApprovalPostDev",
                "ActionTypeId":{
                    "Category":"Approval",
                    "Owner":"AWS",
                    "Version":"1",
                    "Provider":"Manual"
                },
                "RunOrder": 9
            }
            self.parent.stages[0]['Actions'].append(self.action)
            return self.parent

class ManualApprovalPreProd(Builder):

    def __init__(self, parent, context):
        super().__init__(parent, context)
        self.action = {}
    
    def Build(self):
        if not self.manual_approval_preprod:
            return self.parent
        else:
            stage_number = (len(self.environments.items())) - 2
            self.action = {
                "Name":"ManualApprovalPreProd",
                "ActionTypeId":{
                    "Category":"Approval",
                    "Owner":"AWS",
                    "Version":"1",
                    "Provider":"Manual"
                },
                "RunOrder": 9
            }
            self.parent.stages[stage_number]['Actions'].append(self.action)
            return self.parent

class EnvironmentsBuilder(Builder):
    def __init__(self, parent, context):
        super().__init__(parent, context)
        
    def Build(self):
        for env, env_value in self.environments.items():
            actions = []
            env_lower = env.lower()
            if self.sdlc_cloudformation:
                actions.append(
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
                                "Fn::Sub":"arn:aws:iam::" + env_value['AccountId'] + ":role/"+ env_lower + "-${MasterPipeline}-scopes-" + self.scope_lower + "-CloudFormationRole"
                            },
                            "StackName":  env_lower + "-" + self.scope_lower + "-" + self.name_lower if not self.sdlc_stack_name else self.sdlc_stack_name.replace('${Environment}', env_lower),
                            "TemplatePath": "BuildOutput::CloudFormation-SDLC.template" if self.cicd_codebuild else "SourceOutput::CloudFormation-SDLC.template",
                            "TemplateConfiguration": ( "BuildOutput::cfvars/" + env + ".template" if self.include_cf_vars else "SourceOutput::cfvars/" + env + ".template" ) if self.include_cf_vars else { "Ref": "AWS::NoValue" },
                            "ParameterOverrides":{
                                "Fn::Join": [
                                    "",
                                    [
                                        "{",
                                        "\"S3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"BuildOutput\", \"BucketName\"]}, \"S3ObjectKey\" : { \"Fn::GetArtifactAtt\" : [\"BuildOutput\", \"ObjectKey\"]}," if self.cicd_codebuild else
                                            "\"S3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"BucketName\"]}, \"S3ObjectKey\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"ObjectKey\"]},",
                                        {
                                            "Fn::Sub": [
                                                "\"KmsCmkArn\": \"${KmsCmkArn}\",",
                                                {
                                                    "KmsCmkArn": {
                                                        "Fn::GetAtt": [
                                                            "KmsKey",
                                                            "Arn"
                                                        ]
                                                    }
                                                }
                                            ]
                                        },
                                        {
                                            "Fn::Sub": "\"Environment\": \"" + env_lower + "\","
                                        },
                                        {
                                            "Fn::Sub": "\"MasterPipeline\": \"${MasterPipeline}\","
                                        },
                                        {
                                            "Fn::Sub": "\"Scope\": \"" + self.scope_lower + "\","
                                        },
                                        {
                                            "Fn::Sub": "\"SubScope\": \"" + self.name_lower + "\""
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
                            "Fn::Sub":"arn:aws:iam::" + env_value['AccountId'] + ":role/" + env_lower + "-${MasterPipeline}-scopes-" + self.scope_lower + "-CodePipelineRole"
                        }
                    }
                )
            if self.sdlc_ecs:
                actions.append(
                    {
                        "ActionTypeId": {
                            "Category": "Deploy",
                            "Owner": "AWS",
                            "Provider": "ECS",
                            "Version": "1"
                        },
                        "Configuration": {
                            "ClusterName": self.sdlc_ecs_cluster_name,
                            "ServiceName": env_lower + '-' + self.scope_lower + '-' + self.name_lower,
                            "FileName": "imagedefinitions.json"
                        },
                        "Name": "DeployEcs",
                        "InputArtifacts": [
                            { "Name": "BuildOutput" } if self.cicd_codebuild else { "Name": "SourceOutput" }
                        ],
                        "RunOrder": 2,
                        "RoleArn": {
                            "Fn::Sub":"arn:aws:iam::" + env_value['AccountId'] + ":role/" + env_lower + "-${MasterPipeline}-scopes-" + self.scope_lower + "-CodePipelineRole"
                        }
                    }
                )
            if self.sdlc_codebuild:
                actions.append(
                    {
                        "ActionTypeId": {
                            "Category": "Build",
                            "Owner": "AWS",
                            "Provider": "CodeBuild",
                            "Version": "1"
                        },
                        "Configuration": {
                            "ProjectName": {
                                "Fn::Sub": env_lower + "-" + self.scope_lower + "-" + self.name_lower + "-CodeBuild"
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
                            "Fn::Sub":"arn:aws:iam::" + env_value['AccountId'] + ":role/" + env_lower + "-${MasterPipeline}-scopes-" + self.scope_lower + "-CodePipelineRole"
                        }
                    }
                )            
            self.parent.stages.extend(
                [
                    {
                        "Name": env,
                        "Actions": actions
                    }
                ]
            )
        return self.parent

class SdlcStageBuilder(Builder):

    def __init__(self, parent, context):
        super().__init__(parent, context)
        self.stages = []

    def Environments(self):
        return EnvironmentsBuilder(self, self.context)

    def ManualApprovalPostDev(self):
        return ManualApprovalPostDev(self, self.context)

    def ManualApprovalPreProd(self):
        return ManualApprovalPreProd(self, self.context)

    def Build(self):
        self.parent.stages.extend(self.stages)
        return self.parent

class StagesBuilder(Builder):

    def __init__(self, parent, context):
        super().__init__(parent, context)
        self.stages = []

    def Source(self):
        return SourceStageBuilder(self, self.context)

    def Cicd(self):
        return CicdStageBuilder(self, self.context)

    def Sdlc(self):
        return SdlcStageBuilder(self, self.context)
    
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
            "Name": f"{self.scope_lower}-{self.name_lower}",
            "Stages": self.stages
        }
        return self.parent

class Pipeline:

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