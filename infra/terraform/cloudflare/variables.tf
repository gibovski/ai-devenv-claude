variable "account_id" {
  type        = string
  description = "Cloudflare account ID"
}

variable "zone" {
  type        = string
  description = "DNS zone (domain) that hosts the hostname, e.g. example.com"
}

variable "hostname" {
  type        = string
  description = "Public hostname for this environment, e.g. devenv.example.com"
}

variable "tunnel_name" {
  type        = string
  default     = ""
  description = "Tunnel name; defaults to the hostname"
}

variable "origin_service" {
  type        = string
  default     = "http://caddy:80"
  description = "Service cloudflared forwards to, from inside the Docker stack"
}

variable "allowed_emails" {
  type        = list(string)
  default     = []
  description = "People allowed through Cloudflare Access (one-time PIN by email)"
}

variable "service_token_names" {
  type        = list(string)
  default     = ["baz-claude", "chatgpt"]
  description = "Access service tokens for automated controllers (Claude 'Baz', ChatGPT, scripts)"
}

variable "session_duration" {
  type    = string
  default = "24h"
}
