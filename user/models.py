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