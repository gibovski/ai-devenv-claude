# Branch protection for main, as code.
# Apply with: terraform init && terraform apply  (GITHUB_TOKEN needs admin on the repo)
# or run the "repo-settings" workflow with the GH_ADMIN_TOKEN secret set.

terraform {
  required_version = ">= 1.6"
  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.4"
    }
  }
}

provider "github" {
  owner = var.owner
}

variable "owner" {
  type    = string
  default = "gibovski"
}

variable "repository" {
  type    = string
  default = "ai-devenv-claude"
}

variable "required_checks" {
  type    = list(string)
  default = ["shell", "docker", "python", "web", "terraform", "packer", "test"]
}

resource "github_branch_protection" "main" {
  repository_id           = var.repository
  pattern                 = "main"
  enforce_admins          = false
  allows_deletions        = false
  allows_force_pushes     = false
  required_linear_history = false

  required_status_checks {
    strict   = false
    contexts = var.required_checks
  }
}
