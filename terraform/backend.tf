terraform {
  backend "http" {
    address="https://gitlab.example.com/api/v4/projects/bpacc/terraform/state/default"
    lock_address="https://gitlab.example.com/api/v4/projects/bpacc/terraform/state/default/lock"
    unlock_address="https://gitlab.example.com/api/v4/projects/bpacc/terraform/state/default/lock"
  }
}
