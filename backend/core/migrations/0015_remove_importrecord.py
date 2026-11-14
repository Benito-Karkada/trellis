from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0014_login_throttle")]
    operations = [migrations.DeleteModel(name="ImportRecord")]
