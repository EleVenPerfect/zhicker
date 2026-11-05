def register_blueprints(app):
    from . import (
        archive_routes,
        auth_routes,
        collection_routes,
        cookie_routes,
        dashboard_routes,
        epub_routes,
        job_routes,
        settings_routes,
    )

    for module in (
        auth_routes,
        dashboard_routes,
        collection_routes,
        job_routes,
        epub_routes,
        archive_routes,
        cookie_routes,
        settings_routes,
    ):
        app.register_blueprint(module.bp)
