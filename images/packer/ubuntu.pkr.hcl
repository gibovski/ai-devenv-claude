packer {
  required_plugins {
    qemu = {
      source  = "github.com/hashicorp/qemu"
      version = "~> 1.1"
    }
  }
}

variable "arch" {
  type        = string
  default     = "amd64"
  description = "amd64 or arm64"
  validation {
    condition     = contains(["amd64", "arm64"], var.arch)
    error_message = "The arch must be amd64 or arm64."
  }
}

variable "ubuntu_codename" {
  type    = string
  default = "noble"
}

variable "accelerator" {
  type        = string
  default     = "kvm"
  description = "kvm on a native runner, tcg under emulation"
}

variable "disk_size" {
  type    = string
  default = "40G"
}

variable "memory" {
  type    = number
  default = 4096
}

variable "cpus" {
  type    = number
  default = 4
}

variable "version" {
  type    = string
  default = "dev"
}

variable "stack_images_dir" {
  type        = string
  default     = "images-cache"
  description = "Directory of docker save tarballs (*.tar) to bake into the image"
}

locals {
  base_url = "https://cloud-images.ubuntu.com/${var.ubuntu_codename}/current"
  image    = "${var.ubuntu_codename}-server-cloudimg-${var.arch}.img"
  is_arm   = var.arch == "arm64"
  qemu_bin = local.is_arm ? "qemu-system-aarch64" : "qemu-system-x86_64"
  machine  = local.is_arm ? "virt" : "q35"
  efi_code = local.is_arm ? "/usr/share/AAVMF/AAVMF_CODE.fd" : "/usr/share/OVMF/OVMF_CODE_4M.fd"
  efi_vars = local.is_arm ? "/usr/share/AAVMF/AAVMF_VARS.fd" : "/usr/share/OVMF/OVMF_VARS_4M.fd"
  cpu      = var.accelerator == "kvm" ? "host" : (local.is_arm ? "max" : "max")
}

source "qemu" "ubuntu" {
  iso_url          = "${local.base_url}/${local.image}"
  iso_checksum     = "file:${local.base_url}/SHA256SUMS"
  disk_image       = true
  disk_size        = var.disk_size
  format           = "qcow2"
  disk_compression = true

  qemu_binary  = local.qemu_bin
  machine_type = local.machine
  accelerator  = var.accelerator
  cpus         = var.cpus
  memory       = var.memory
  headless     = true
  qemuargs     = [["-cpu", local.cpu]]

  efi_boot          = true
  efi_firmware_code = local.efi_code
  efi_firmware_vars = local.efi_vars

  net_device     = "virtio-net"
  disk_interface = "virtio"

  cd_files = ["${path.root}/http/user-data", "${path.root}/http/meta-data"]
  cd_label = "cidata"

  communicator     = "ssh"
  ssh_username     = "dev"
  ssh_password     = "packer-build"
  ssh_timeout      = var.accelerator == "kvm" ? "20m" : "90m"
  shutdown_command = "sudo shutdown -P now"

  output_directory = "output-${var.arch}"
  vm_name          = "devenv-${var.version}-${var.arch}.qcow2"
}

build {
  sources = ["source.qemu.ubuntu"]

  provisioner "shell" {
    inline = ["cloud-init status --wait || true"]
  }

  provisioner "file" {
    source      = "${path.root}/../../stack"
    destination = "/tmp/stack"
  }

  provisioner "file" {
    source      = "${path.root}/files"
    destination = "/tmp/files"
  }

  provisioner "file" {
    source      = "${path.root}/../../infra/terraform/cloudflare"
    destination = "/tmp/terraform-cloudflare"
  }

  provisioner "file" {
    source      = "${path.root}/../../mcp"
    destination = "/tmp/mcp"
  }

  provisioner "shell" {
    execute_command = "{{ .Vars }} sudo -E bash '{{ .Path }}'"
    environment_vars = [
      "DEBIAN_FRONTEND=noninteractive",
      "DEVENV_VERSION=${var.version}",
      "DEVENV_ARCH=${var.arch}",
    ]
    scripts = [
      "${path.root}/scripts/10-base.sh",
      "${path.root}/scripts/20-docker.sh",
      "${path.root}/scripts/30-devtools.sh",
      "${path.root}/scripts/40-stack.sh",
    ]
  }

  provisioner "file" {
    source      = "${var.stack_images_dir}/"
    destination = "/tmp/stack-images"
  }

  provisioner "shell" {
    execute_command = "sudo -E bash '{{ .Path }}'"
    scripts = [
      "${path.root}/scripts/50-preload-images.sh",
      "${path.root}/scripts/90-cleanup.sh",
    ]
  }

  provisioner "file" {
    direction   = "download"
    sources     = ["/var/tmp/packages.tsv", "/var/tmp/images.txt"]
    destination = "output-${var.arch}/"
  }

  provisioner "shell" {
    inline = ["sudo rm -f /var/tmp/packages.tsv /var/tmp/images.txt"]
  }
}
