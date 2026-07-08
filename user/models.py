from django.db import models
from django.contrib.auth.models import AbstractUser
from phonenumber_field.modelfields import PhoneNumberField


class User(AbstractUser):
    username = models.CharField(unique=True,max_length=20,verbose_name="نام کاربری")
    phone_number = PhoneNumberField(unique=True, verbose_name="شماره تلفن")
    is_verified = models.BooleanField(default=False, verbose_name="تایید شده")
    gender = models.CharField(choices=[('M', 'مرد'), ('F', 'زن')], max_length=1, verbose_name="جنسیت")
    class Meta:
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"

    def __str__(self):
        if self.username:
            return self.username
        return f"{self.id}"

class Address(models.Model):
    user         = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses", verbose_name="کاربر")
    first_name   = models.CharField(max_length=100, verbose_name="نام")
    last_name    = models.CharField(max_length=100, verbose_name="نام خانوادگی")
    province     = models.CharField(max_length=50, verbose_name="استان")
    city         = models.CharField(max_length=50, verbose_name="شهر")
    postal_code  = models.CharField(max_length=10, verbose_name="کد پستی")
    address_line = models.TextField(verbose_name="آدرس")
    is_default   = models.BooleanField(default=False)
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
    class Meta:
        verbose_name = "آدرس"
        verbose_name_plural = "آدرس‌ها"