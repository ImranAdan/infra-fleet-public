"""WSGI entry point for production deployment."""

from load_harness.app import create_app

app = create_app()

if __name__ == "__main__":
    app.run()