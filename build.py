from ..keelback import keelback

keelback.export_static_site(
    "../memex/content", "../memex/static", "../memex/templates", "./docs"
)
print("done")
