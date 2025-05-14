import os
import subprocess
import yaml
import docker
from tools import print_info, print_error


class DockerAppManager:
    def __init__(
        self,
        project_dir,
        image_name="my-app",
        container_name="my-app-container",
        host_port=3000,
    ):
        self.project_dir = os.path.join(os.getcwd(), project_dir)
        self.image_name = image_name
        self.container_name = container_name
        self.host_port = host_port
        self.override_path = os.path.join(
            self.project_dir, "docker-compose.override.yml"
        )
        self.client = docker.from_env()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop_and_remove()

    def _use_docker_compose(self):
        return os.path.exists(os.path.join(self.project_dir, "docker-compose.yml"))

    def _get_exposed_port_from_image(self, image):
        exposed_ports = image.attrs.get("Config", {}).get("ExposedPorts", {})
        if not exposed_ports:
            return None
        return int(list(exposed_ports.keys())[0].split("/")[0])

    def _extract_compose_info(self):
        try:
            with open(os.path.join(self.project_dir, "docker-compose.yml"), "r") as f:
                data = yaml.safe_load(f)
                version = data.get("version", "3")
                services = data.get("services", {})
                if not services:
                    raise ValueError("No services defined.")
                service_names = list(services.keys())
                return version, service_names
        except Exception as e:
            raise RuntimeError(f"Failed to parse docker-compose.yml: {e}")

    def build_and_run(self):
        status = self.stop_and_remove()

        if status[0] != 0:
            print_error(status[1])

        if self._use_docker_compose():
            print_info("Using Docker Compose...")

            try:
                subprocess.run(
                    ["docker-compose", "up", "-d"],
                    cwd=self.project_dir,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

                print_info("Starting container relaods")

                # Post-start check: validate services and fetch logs if any service failed
                version, service_names = self._extract_compose_info()
                project_name = os.path.basename(self.project_dir)

                for service in service_names:
                    container_name = f"{project_name}-{service}-1"

                    try:
                        print_info(f"Reloading: {container_name}")
                        container = self.client.containers.get(container_name)
                        container.reload()

                        if container.status != "running":
                            logs = container.logs(tail=100).decode(errors="replace")
                            error_message = f"Service '{service}' failed to start.\nStatus: {container.status}\nLogs:\n{logs}"
                            return (8, error_message)

                    except docker.errors.NotFound:
                        error_message = f"Container '{container_name}' not found after docker-compose up."
                        return (9, error_message)
                    except docker.errors.APIError as e:
                        error_message = (
                            f"Error inspecting container '{container_name}': {e}"
                        )
                        return (10, error_message)

                return (
                    0,
                    f"All containers started successfully on http://localhost:{self.host_port}.",
                )

            except subprocess.CalledProcessError as e:
                error_message = f"Docker Compose error: {e}\n"
                error_message += (
                    f"Standard Output: {e.stdout.decode()}\n" if e.stdout else ""
                )
                error_message += (
                    f"Standard Error: {e.stderr.decode()}\n" if e.stderr else ""
                )
                return 3, error_message

        else:
            print_info("Using Dockerfile directly...")

            try:
                image, _ = self.client.images.build(
                    path=self.project_dir, tag=self.image_name
                )
            except docker.errors.BuildError as e:
                logs = [line.get("stream", "") for line in e.build_log]
                build_log = "".join(logs[-50:])
                return 4, f"Docker build failed: {e}, build log:\n {build_log}"
            except docker.errors.APIError as e:
                return 5, f"Docker API error: {e}"

            container_port = self._get_exposed_port_from_image(image)
            if not container_port:
                return 6, "No EXPOSED port found in Dockerfile."

            try:
                self.client.containers.run(
                    image=self.image_name,
                    name=self.container_name,
                    ports={f"{container_port}/tcp": self.host_port},
                    detach=True,
                    remove=True,
                )

                return 0, f"Container started on http://localhost:{self.host_port}."
            except docker.errors.APIError as e:
                return 7, f"Failed to start container: {e}"

    def stop_and_remove(self):
        if self._use_docker_compose():
            try:
                subprocess.run(
                    ["docker-compose", "down", "-v"], cwd=self.project_dir, check=True
                )
            except subprocess.CalledProcessError as e:
                return 1, f"Error stopping containers: {e}"
        else:
            try:
                container = self.client.containers.get(self.container_name)
                container.stop()
            except docker.errors.NotFound:
                return 2, "Container not found."
            except docker.errors.APIError as e:
                return 3, f"Failed to stop container: {e}"

        # Delete override file if it exists
        if os.path.exists(self.override_path):
            try:
                os.remove(self.override_path)
                print_info(f"Deleted override file: {self.override_path}")
            except Exception as e:
                return 4, f"Failed to delete override file: {e}"

        return 0, "All stopped and cleaned up successfully."
