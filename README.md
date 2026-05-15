# Smart Home Backend

A backend API for managing a smart home environment, built with Python and FastAPI.

## Project Structure

- `app/`: Contains the FastAPI application code (models, routers, main app file).
- `k8s/`: Contains Kubernetes deployment manifests (`deployment.yaml`, etc.).
- `Dockerfile`: Defines the Docker image for the application.
- `requirements.txt`: Python dependencies.

## Technologies Used

- **FastAPI**: Modern, fast web framework for building APIs with Python.
- **Docker**: For containerizing the application.
- **Kubernetes**: For orchestrating the containers and ensuring high availability.

## Getting Started (Local Development)

1. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the development server:
   ```bash
   uvicorn app.main:app --reload
   ```

The API will be available at `http://localhost:8000`.
You can access the interactive API documentation (Swagger UI) at `http://localhost:8000/docs`.

## Deployment (Kubernetes)

This project is configured to run on Kubernetes. 

1. Ensure your Kubernetes cluster is running and your `kubectl` is configured.
2. Build your Docker image (if you haven't already):
   ```bash
   docker build -t denniszo/smart-home-backend:latest .
   ```
3. Apply the Kubernetes manifests:
   ```bash
   kubectl apply -f k8s/deployment.yaml
   ```
4. Verify the deployment:
   ```bash
   kubectl get pods
   kubectl get services
   ```
