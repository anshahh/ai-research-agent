variable "db_username" {
  description = "Master username for the Postgres instance"
  type        = string
  default     = "agent_admin"
}

variable "db_password" {
  description = "Master password for the Postgres instance"
  type        = string
  sensitive   = true
}

variable "allowed_ip" {
  description = "Your public IP, allowed to connect to the database (CIDR format, e.g. 1.2.3.4/32)"
  type        = string
}
