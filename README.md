# Pipes
A pipeline ..... for managing your pipelines.

The purpose of this project is to manage many CodePipeline's within an organization across multiple accounts. Each pipeline belongs to an infrastructure "Scope" that logically separates the permissions of each pipeline via seperate S3 buckets and KMS keys. 

## Architecture Diagram
![Diagram](https://farrantch.github.io/pipes.png)

## Set up the master pipeline
By default, this uses 3 AWS environments (ideally seperated accounts):
   - cicd
   - dev
   - prod

Within the cicd account, run Master.template through CloudFormation.
   - Name the stack "master" or something similar (lowercase)
   - Input Id's for each environment's account
   - Set AllEnvironmentsCreated = False
   - Leave SourceCodeCommitRepo empty
   
Once finished, copy the KmsCmkArn and S3BucketName from the CloudFormation outputs section.
    
With the cicd, dev, and prod accounts, run Master-Environment.template through CloudFormation.
   - Name the stack ${Environment}-{MasterStackName} ***important!*** ie: cicd-master 
   - Pass in the KmsCmkArn and S3BucketName as parameters
   - Set environment (lowercase)
   - Set AccountId of cicd account
   - Pass in name of master stack (lowercase)

After SDLC stacks have been created, update the master stack within the cicd account.
   - Set AllEnvironmentsCreated = True
   
Copy this repo into the empty CodeCommit repo created by the master stack.
   - Update the cfvars/Master.template file with your account ids.

## Child Pipelines
Edit your Pipelines.template file as needed. Enjoy!

## To-Do
   - Environments.template to define environments instead of defaults
   - Ability to pull pipeline source repos from github
   - Add optional deploy to ECS step
   - YAML support?
