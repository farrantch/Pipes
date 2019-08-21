# Pipes
The purpose of this project is to easily manage AWS cross-account permissions that have traditionally been difficult to automate and maintain.
One might assume that because most software companies follow the same SDLC process, that this framework should have already existed. But alas..

What this manages:
   -  

## Architecture Diagram
![Diagram](https://farrantch.github.io/pipes.png)

## Set up the master pipeline
Within your cicd account, run Master.template through CloudFormation.
   - Name the stack "master" or something similar (lowercase)
   - Set AllEnvironmentsCreated = False
   - Leave SourceCodeCommitRepo blank to create a repo. Fill with "codecommit:repo-name" to point to an existing repo. Fill with "github:repo-url:key" to link to a github repo.
   
Once finished, copy the KmsCmkArn and S3BucketName from the CloudFormation outputs section.
    
For every SDLC environment (aka: cicd, dev, qa, prod), run the Master-Environment.template through CloudFormation. The cicd environment is required! All others are optional.
   - Name the stack ${Environment}-{MasterStackName} ie: cicd-master (lowercase)
   - Pass in the KmsCmkArn and S3BucketName as parameters
   - Set environment (lowercase)
   - Set AccountId of cicd account
   - Pass in name of master stack (lowercase)

After SDLC stacks have been created, do the following:
   - Copy this repo into the source CodeCommit repo we configured for the master pipeline.
   - remove the ".example" from the Config-* file names.
   - Update the cfvars/Master.template file with your account ids.
   - Configure the
   - Set AllEnvironmentsCreated = True

## Child Pipelines
Edit your Pipelines.template file as needed. Enjoy!

## To-Do
   - Option to store GitHub key elsewhere.
   - Add optional deploy to ECS step
   - Cross Region support
   - Inline policies
   - YAML support?
   - Ability to have master pipeline in separate account than CICD account
   - Ability for pipelines to self update

