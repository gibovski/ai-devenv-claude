terraform {
  required_version = ">= 1.6"
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.10"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
  # State lives in a Cloudflare R2 bucket; tf.sh passes the endpoint and credentials.
  backend "s3" {}
}

provider "cloudflare" {
  # Reads CLOUDFLARE_API_TOKEN from the environment.
}
