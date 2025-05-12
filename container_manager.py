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

        if not status[0]:
            print_error(status[1])

        if self._use_docker_compose():
            print_info("Using Docker Compose...")

            try:
                image, _ = self.client.images.build(
                    path=self.project_dir, tag=self.image_name
                )
            except docker.errors.BuildError as e:
                logs = [line.get("stream", "") for line in e.build_log]
                print_info("Docker build failed. Last 30 lines of log:")
                build_log = "".join(logs[-30:])
                print_error("\n" + build_log)
                return 4, f"Docker build failed: {e}, build log:\n {build_log}"
            except docker.errors.APIError as e:
                return 5, f"Docker API error: {e}"

            container_port = self._get_exposed_port_from_image(image)
            if not container_port:
                return 6, "No EXPOSED port found in Dockerfile."

            try:
                version, service_names = self._extract_compose_info()
                if not os.path.exists(self.override_path):
                    with open(self.override_path, "w") as f:
                        for i, service in enumerate(service_names):
                            f.write(f"  {service}:\n")
                            if i == 0:  # Bind only the first service (frontend)
                                f.write(f"    ports:\n")
                                f.write(f'      - "{self.host_port}:{container_port}"\n')
                    print_info(f"Override file created: {self.override_path}")
            except Exception as e:
                return 2, f"Failed to generate override file: {e}"

            try:
                logs = subprocess.run(
                    ["docker-compose", "up", "-d"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                return 0, f"Containers started on localhost:{self.host_port}."
            except subprocess.CalledProcessError as e:
                error_message = f"Docker Compose error: {e}\n"
                error_message += f"Standard Output: {e.stdout.decode()}\n" if e.stdout else ""
                error_message += f"Standard Error: {e.stderr.decode()}\n" if e.stderr else ""
                return 3, error_message

        else:
            print_info("Using Dockerfile directly...")

            try:
                image, _ = self.client.images.build(
                    path=self.project_dir, tag=self.image_name
                )
            except docker.errors.BuildError as e:
                logs = [line.get("stream", "") for line in e.build_log]
                print_info("Docker build failed. Last 30 lines of log:")
                build_log = "".join(logs[-30:])
                print_error("\n" + build_log)
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
                subprocess.run(["docker-compose", "down"], check=True)
            except subprocess.CalledProcessError as e:
                return 1, f"Error stopping containers: {e}"
        else:
            try:
                container = self.client.containers.get(self.container_name)
                container.stop()
                # container.remove()
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

        # Remove the associated image
        try:
            # self.client.images.remove(image=self.image_name, force=True)
            print_info(f"Deleted image: {self.image_name}")
        except docker.errors.ImageNotFound:
            return 5, f"Image '{self.image_name}' not found."
        except docker.errors.APIError as e:
            return 6, f"Failed to delete image: {e}"

        return 0, "All stopped, images removed, and cleaned up successfully."
