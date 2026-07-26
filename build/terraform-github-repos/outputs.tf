################################################################################
# outputs.tf — Values printed after terraform apply
################################################################################

output "repository_urls" {
  description = "HTML URLs for all managed repositories"
  value = {
    PostgreDataMigrationApp = github_repository.postgres_data_migration_app.html_url
  }
}

output "repository_clone_urls" {
  description = "HTTPS clone URLs for all managed repositories"
  value = {
    PostgreDataMigrationApp = github_repository.postgres_data_migration_app.http_clone_url
  }
}

output "repository_ssh_urls" {
  description = "SSH clone URLs for all managed repositories"
  value = {
    PostgreDataMigrationApp = github_repository.postgres_data_migration_app.ssh_clone_url
  }
}
