https://github.com/innopam/geo-registration
# Airflow Ortho Project

This project uses Apache Airflow to manage and orchestrate workflows for the Ortho application.

## Prerequisites

- Python 3.7+
- Apache Airflow 2.0+
- Docker (optional, for containerized deployment)

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/yourusername/airflow-ortho.git
   cd airflow-ortho
   ```

2. Create a virtual environment and activate it:

   ```bash
   pyenv virtualenv 3.11.2 airflow-ortho
   ```

   ```bash
   pyenv activate airflow-ortho
   ```

3. Install the required dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Initialize the Airflow database:
   ```bash
   airflow db init
   ```

## Configuration

1. Set up the Airflow configuration file (`airflow.cfg`) as needed.
2. Define your DAGs in the `d₩ags/` directory.

## Running Airflow

1. Start the Airflow web server:

   ```bash
   airflow webserver --port 8080
   ```

2. Start the Airflow scheduler:

   ```bash
   airflow scheduler
   ```

3. Access the Airflow UI by navigating to `http://localhost:8080` in your web browser.

## Deployment

For containerized deployment, use the provided `Dockerfile` and `docker-compose.yml` to build and run the application.

## Contributing

Please read `CONTRIBUTING.md` for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the MIT License - see the `LICENSE` file for details.

## Acknowledgments

- Apache Airflow
- Docker
