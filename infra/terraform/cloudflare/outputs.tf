output "tunnel_id" {
  value = cloudflare_zero_trust_tunnel_cloudflared.this.id
}

output "tunnel_token" {
  value     = data.cloudflare_zero_trust_tunnel_cloudflared_token.this.token
  sensitive = true
}

output "url" {
  value = "https://${var.hostname}"
}

output "service_tokens" {
  description = "Send as CF-Access-Client-Id / CF-Access-Client-Secret headers"
  value       = { for k, t in cloudflare_zero_trust_access_service_token.controller : k => { client_id = t.client_id, client_secret = t.client_secret } }
  sensitive   = true
}
