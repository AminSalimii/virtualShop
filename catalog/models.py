from django.db import models
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.conf import settings

protected_storage = FileSystemStorage(location=settings.PROTECTED_MEDIA_ROOT)


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")


class Item(models.Model):
    PHYSICAL, DIGITAL = "physical", "digital"
    ITEM_TYPE_CHOICES = [(PHYSICAL, "فیزیکی"), (DIGITAL, "دیجیتال")]

    title       = models.CharField(max_length=255)
    slug        = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    category    = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="items")
    item_type   = models.CharField(max_length=10, choices=ITEM_TYPE_CHOICES)

    price          = models.DecimalField(max_digits=12, decimal_places=0)  # Toman — whole numbers
    discount_price = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True)
    is_active      = models.BooleanField(default=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    # Physical-only
    stock_quantity = models.PositiveIntegerField(null=True, blank=True)
    weight_grams   = models.PositiveIntegerField(null=True, blank=True)

    # Digital-only
    digital_file = models.FileField(
        upload_to="digital_items/", storage=protected_storage, null=True, blank=True
    )
    max_downloads = models.PositiveIntegerField(null=True, blank=True)

    def clean(self):
        if self.item_type == self.PHYSICAL and self.stock_quantity is None:
            raise ValidationError("Physical items require stock_quantity.")
        if self.item_type == self.DIGITAL and not self.digital_file:
            raise ValidationError("Digital items require a digital_file.")

class ItemImage(models.Model):
    item       = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="images")
    image      = models.ImageField(upload_to="item_images/")
    is_primary = models.BooleanField(default=False)
