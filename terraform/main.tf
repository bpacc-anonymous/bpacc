module "cluster" {
  source = "gitlab.example.com/bpacc/rke2-cluster/local"
  version = "0.0.5"

  cluster_name                    = "bpacc"
  k8s_version                     = "v1.33.7+rke2r1"
  vm_namespace                    = "bpacc"
  vm_master_count                 = 3
  vm_worker_count                 = 3
  vm_template_master_cpu_count    = 4
  vm_template_master_memory_size  = 16
  vm_template_worker_cpu_count    = 8
  vm_template_worker_memory_size  = 32
  vm_template_image_name          = "harvester-public/image-x9skt"
  vm_template_disk_size           = 60
  vm_template_network_name        = "harvester-public/network-vlan-208"
  vm_template_ssh_user            = "almalinux"
  harvester_cluster               = "harvester-production"
  harvester_cluster_id            = "c-k6sjf"
  rancher_access_key              = var.rancher_access_key
  rancher_secret_key              = var.rancher_secret_key
  rancher_url                     = var.rancher_url
}
