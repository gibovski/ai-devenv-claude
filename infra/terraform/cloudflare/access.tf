# Cloudflare Access: people log in with an email one-time PIN; controllers use service tokens.
# /mcp is token-protected by the control plane, so it bypasses Access for cloud-hosted assistants
# (claude.ai, ChatGPT) that cannot send Access headers.

resource "cloudflare_zero_trust_access_service_token" "controller" {
  for_each   = toset(var.service_token_names)
  account_id = var.account_id
  name       = "${local.tunnel_name}-${each.key}"
  duration   = "8760h"
}

resource "cloudflare_zero_trust_access_policy" "people" {
  count      = length(var.allowed_emails) > 0 ? 1 : 0
  account_id = var.account_id
  name       = "${local.tunnel_name} people"
  decision   = "allow"
  include    = [for e in var.allowed_emails : { email = { email = e } }]
}

resource "cloudflare_zero_trust_access_policy" "controllers" {
  count      = length(var.service_token_names) > 0 ? 1 : 0
  account_id = var.account_id
  name       = "${local.tunnel_name} controllers"
  decision   = "non_identity"
  include    = [for t in cloudflare_zero_trust_access_service_token.controller : { service_token = { token_id = t.id } }]
}

resource "cloudflare_zero_trust_access_policy" "mcp_bypass" {
  account_id = var.account_id
  name       = "${local.tunnel_name} mcp bypass"
  decision   = "bypass"
  include    = [{ everyone = {} }]
}

resource "cloudflare_zero_trust_access_application" "site" {
  account_id       = var.account_id
  name             = local.tunnel_name
  domain           = var.hostname
  type             = "self_hosted"
  session_duration = var.session_duration
  policies = concat(
    [for i, p in cloudflare_zero_trust_access_policy.people : { id = p.id, precedence = 1 + i }],
    [for i, p in cloudflare_zero_trust_access_policy.controllers : { id = p.id, precedence = 10 + i }],
  )
}

resource "cloudflare_zero_trust_access_application" "mcp" {
  account_id       = var.account_id
  name             = "${local.tunnel_name} mcp"
  domain           = "${var.hostname}/mcp"
  type             = "self_hosted"
  session_duration = var.session_duration
  policies         = [{ id = cloudflare_zero_trust_access_policy.mcp_bypass.id, precedence = 1 }]
}
