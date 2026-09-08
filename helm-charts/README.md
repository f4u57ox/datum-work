# Datum Work deployment configuration

The charts retain their upstream `stratum-work-*` names and default image repositories for compatibility. When deploying Datum Work, override `image.repository` and `image.tag` for every chart with images built from this fork. The collector Helmfile also has an image repository override; update it when using that deployment path.

The collector and webapp release workflows publish only when their corresponding GitHub repository variable is set:

| Repository variable | Docker Hub repository example |
| --- | --- |
| `DATUM_COLLECTOR_IMAGE` | `your-dockerhub-account/datum-work-collector` |
| `DATUM_WEBAPP_IMAGE` | `your-dockerhub-account/datum-work-webapp` |

Configure `DOCKER_USERNAME` and `DOCKER_PASSWORD` repository secrets for an account with permission to publish to those repositories. Publishing a GitHub release builds and pushes the `latest` and release-tagged images. If an image variable is empty, its publishing job is skipped. There is no backend publishing workflow; build and publish the backend image separately before selecting it in Helm.

For example, after publishing a webapp image:

```sh
helm upgrade --install datum-work-webapp ./helm-charts/stratum-work-webapp \
  --set image.repository=your-dockerhub-account/datum-work-webapp \
  --set image.tag=YOUR_RELEASE_TAG \
  -f /path/to/your/deployment-values.yaml
```

Use deployment-specific values for database, RabbitMQ, and Bitcoin node connection settings. The webapp `env.DATABASE_URL` is a credential-free example pointing to a service named `mongodb`; replace it with the connection string for your installation. Keep credentials out of committed values files.
