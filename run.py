import os
from app import create_app
from app.ml.registry import registry

app = create_app()

if __name__ == "__main__":
    # Debug + bind host are env-driven and SAFE BY DEFAULT:
    #   - debug is OFF unless FLASK_DEBUG=1 (the Werkzeug debugger is a remote
    #     code-execution console — never enable it on a shared network).
    #   - host binds to localhost unless FLASK_HOST is set (e.g. 0.0.0.0).
    debug = os.getenv("FLASK_DEBUG", "0").lower() in ("1", "true", "yes", "on")
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    # use_reloader=False so heavy models aren't loaded twice (watcher + child).
    try:
        app.run(host=host, port=5000, debug=debug, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        registry.free_all()
