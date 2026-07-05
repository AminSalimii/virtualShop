import re
from django.conf import settings
from django.core.cache import cache
from rest_framework import serializers
from rest_framework import serializers
from django.contrib.auth import authenticate, get_user_model
from phonenumber_field.serializerfields import PhoneNumberField
from django.contrib.auth.password_validation import validate_password


User = get_user_model()

 

#──────────────────────────────────────────────
#  Sign In
# ──────────────────────────────────────────────
 
class SignInSerializer(serializers.Serializer):
    """
    Validates username/password credentials and authenticates the user.
    On success, the authenticated user instance is available as
    `validated_data["user"]`.
    """
 
    username = serializers.CharField(write_only=True)
    password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
        trim_whitespace=False,
    )
 
    def validate(self, attrs):
        username = attrs.get("username")
        password = attrs.get("password")
 
        user = authenticate(
            request=self.context.get("request"),
            username=username,
            password=password,
        )
 
        if user is None:
            raise serializers.ValidationError(
                {"detail": "نام کاربری یا رمز عبور اشتباه است."},
                code="authorization",
            )
 
        # if not user.is_active:
        #     raise serializers.ValidationError(
        #         {"detail": "این حساب کاربری غیرفعال است."},
        #         code="authorization",
        #     )
 
        # if not user.is_verified:
        #     raise serializers.ValidationError(
        #         {"detail": "شماره تلفن شما تایید نشده است. ابتدا OTP را تایید کنید."},
        #         code="authorization",
        #     )
 
        attrs["user"] = user
        return attrs
 
 
# ──────────────────────────────────────────────
#  Registration
# ──────────────────────────────────────────────
 
class RegisterSerializer(serializers.ModelSerializer):
    """
    Creates a new inactive (unverified) user.
    After registration the client must complete the OTP flow
    (POST /api/auth/otp/request/ → POST /api/auth/otp/verify/)
    before they can sign in.
    """
 
    password  = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
        trim_whitespace=False,
    )
    password2 = serializers.CharField(
        write_only=True,
        label="تکرار رمز عبور",
        style={"input_type": "password"},
        trim_whitespace=False,
    )
    phone_number = PhoneNumberField()
 
    class Meta:
        model  = User
        fields = ["username", "phone_number", "password", "password2", "gender"]
 
    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("این نام کاربری قبلاً استفاده شده است.")
        return value
 
    def validate_phone_number(self, value):
        if User.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError("این شماره تلفن قبلاً ثبت شده است.")
        return value
 
    def validate(self, attrs):
        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError(
                {"password2": "رمز عبور و تکرار آن یکسان نیستند."}
            )
        return attrs
 
    def create(self, validated_data):
        validated_data.pop("password2")
        password = validated_data.pop("password")
 
        user = User(**validated_data)
        user.set_password(password)   # hashes the password correctly
        user.is_verified = False       # must verify phone before signing in
        user.is_active   = True
        user.save()
        return user
 
 
# ──────────────────────────────────────────────
#  Shared user response
# ──────────────────────────────────────────────
 
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model  = User
        fields = ["id", "username", "phone_number", "gender", "is_verified"]
        read_only_fields = fields




OTP_EXPIRY_SECONDS   = getattr(settings, "OTP_EXPIRY_SECONDS",   120)  # 2 min
OTP_THROTTLE_SECONDS = getattr(settings, "OTP_THROTTLE_SECONDS",  60)  # 1 min
 
 
def _otp_key(phone: str) -> str:
    return f"otp:{phone}"
 
def _throttle_key(phone: str) -> str:
    return f"otp_throttle:{phone}"
 
 
# ─────────────────────────────────────────────────────────
#  Step 1 — Request OTP
# ─────────────────────────────────────────────────────────
 
class RequestOTPSerializer(serializers.Serializer):
    phone_number = PhoneNumberField()
 
    def validate_phone_number(self, value):
        phone_number = str(value)  # e.g. '+989123456789'
 
        # Throttle: one OTP request per OTP_THROTTLE_SECONDS
        if cache.get(_throttle_key(phone_number)):
            raise serializers.ValidationError(
                f"لطفاً {OTP_THROTTLE_SECONDS} ثانیه صبر کنید و دوباره امتحان کنید."
            )
 
        return value
 
 
# ─────────────────────────────────────────────────────────
#  Step 2 — Verify OTP
# ─────────────────────────────────────────────────────────
 
class VerifyOTPSerializer(serializers.Serializer):
    phone_number = PhoneNumberField()
    otp          = serializers.CharField(min_length=6, max_length=6)
 
    def validate(self, attrs):
        phone = str(attrs["phone_number"])
        otp   = attrs["otp"].strip()
 
        stored = cache.get(_otp_key(phone))
 
        if stored is None:
            raise serializers.ValidationError(
                {"otp": "کد تایید منقضی شده یا ارسال نشده است. دوباره درخواست دهید."}
            )
 
        if stored != otp:
            raise serializers.ValidationError(
                {"otp": "کد تایید اشتباه است."}
            )
 
        # ── OTP is correct — consume it immediately (one-time use) ──
        cache.delete(_otp_key(phone))
 
        # ── Resolve user (create if first login) ──────────────────
        user, _ = User.objects.get_or_create(
            phone_number=attrs["phone_number"],
            defaults={"username": phone},
        )
 
        attrs["user"] = user
        return attrs
 
 


#─────────────────────────────────────────────────
#  Redis key helpers
# ─────────────────────────────────────────────────
 
def pwd_otp_key(uid):        return f"pwd_change_otp:{uid}"
def pwd_throttle_key(uid):   return f"pwd_change_throttle:{uid}"
def phone_old_otp_key(uid):  return f"phone_old_otp:{uid}"
def phone_new_otp_key(uid):  return f"phone_new_otp:{uid}"
def phone_new_key(uid):      return f"phone_new_phone:{uid}"
def phone_verified_key(uid): return f"phone_old_verified:{uid}"
def phone_throttle_key(uid): return f"phone_throttle:{uid}"
 
 
# ─────────────────────────────────────────────────
#  Profile view / edit
# ─────────────────────────────────────────────────
 
class ProfileSerializer(serializers.ModelSerializer):
    """
    Readable and editable profile fields.
    phone_number and is_verified are read-only — both have dedicated endpoints.
    """
 
    phone_number = PhoneNumberField(read_only=True)
 
    class Meta:
        model  = User
        fields = [
            "id", "username", "first_name", "last_name",
            "email", "gender", "phone_number", "is_verified",
        ]
        read_only_fields = ["id", "phone_number", "is_verified"]
 
    def validate_username(self, value):
        user = self.context["request"].user
        if User.objects.exclude(pk=user.pk).filter(username=value).exists():
            raise serializers.ValidationError("این نام کاربری قبلاً استفاده شده است.")
        return value
 
    def validate_email(self, value):
        user = self.context["request"].user
        if User.objects.exclude(pk=user.pk).filter(email=value).exists():
            raise serializers.ValidationError("این ایمیل قبلاً ثبت شده است.")
        return value
 
 
# ─────────────────────────────────────────────────
#  Password change — step 1
# ─────────────────────────────────────────────────
 
class ChangePasswordRequestSerializer(serializers.Serializer):
    """
    Validates the user's current password.
    If correct, the view generates an OTP and sends it to their phone.
    """
 
    current_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
        trim_whitespace=False,
    )
 
    def validate_current_password(self, value):
        user = self.context["request"].user
 
        # Throttle: prevent spamming OTP requests
        if cache.get(pwd_throttle_key(user.pk)):
            raise serializers.ValidationError(
                "لطفاً کمی صبر کنید و دوباره امتحان کنید."
            )
 
        if not user.check_password(value):
            raise serializers.ValidationError("رمز عبور فعلی اشتباه است.")
 
        return value
 
 
# ─────────────────────────────────────────────────
#  Password change — step 2
# ─────────────────────────────────────────────────
 
class ChangePasswordConfirmSerializer(serializers.Serializer):
    """
    Validates the OTP + the new password.
    On success, the view applies the new password and clears the OTP.
    """
 
    otp          = serializers.CharField(min_length=6, max_length=6)
    new_password  = serializers.CharField(
        write_only=True,
        min_length=8,
        style={"input_type": "password"},
        trim_whitespace=False,
    )
    new_password2 = serializers.CharField(
        write_only=True,
        label="تکرار رمز عبور جدید",
        style={"input_type": "password"},
        trim_whitespace=False,
    )
 
    def validate_otp(self, value):
        user       = self.context["request"].user
        stored_otp = cache.get(pwd_otp_key(user.pk))
 
        if stored_otp is None:
            raise serializers.ValidationError(
                "کد تایید منقضی شده است. دوباره درخواست دهید."
            )
        if stored_otp != value.strip():
            raise serializers.ValidationError("کد تایید اشتباه است.")
 
        return value
 
    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password2"]:
            raise serializers.ValidationError(
                {"new_password2": "رمز عبور جدید و تکرار آن یکسان نیستند."}
            )
 
        # Run Django's built-in password validators
        user = self.context["request"].user
        validate_password(attrs["new_password"], user=user)
 
        return attrs
 
 
# ─────────────────────────────────────────────────
#  Phone change — step 1
# ─────────────────────────────────────────────────
 
class ChangePhoneRequestSerializer(serializers.Serializer):
    """
    Accepts the new phone number.
    Sends an OTP to the user's CURRENT (old) phone to prove ownership.
    """
 
    new_phone_number = PhoneNumberField()
 
    def validate_new_phone_number(self, value):
        user = self.context["request"].user
 
        # Throttle
        if cache.get(phone_throttle_key(user.pk)):
            raise serializers.ValidationError(
                "لطفاً کمی صبر کنید و دوباره امتحان کنید."
            )
 
        # Must not already be taken
        if User.objects.exclude(pk=user.pk).filter(phone_number=value).exists():
            raise serializers.ValidationError(
                "این شماره قبلاً توسط حساب دیگری ثبت شده است."
            )
 
        # Must be different from the current phone
        if user.phone_number == value:
            raise serializers.ValidationError(
                "شماره جدید با شماره فعلی یکسان است."
            )
 
        return value
 
 
# ─────────────────────────────────────────────────
#  Phone change — step 2
# ─────────────────────────────────────────────────
 
class ChangePhoneVerifyOldSerializer(serializers.Serializer):
    """
    Validates the OTP that was sent to the OLD phone.
    On success the view marks old phone as verified and sends OTP to the new one.
    """
 
    otp = serializers.CharField(min_length=6, max_length=6)
 
    def validate_otp(self, value):
        user       = self.context["request"].user
        stored_otp = cache.get(phone_old_otp_key(user.pk))
 
        if stored_otp is None:
            raise serializers.ValidationError(
                "کد تایید منقضی شده است. دوباره درخواست دهید."
            )
        if stored_otp != value.strip():
            raise serializers.ValidationError("کد تایید اشتباه است.")
 
        # Ensure a new phone was actually stored from step 1
        if not cache.get(phone_new_key(user.pk)):
            raise serializers.ValidationError(
                "جلسه تغییر شماره منقضی شده است. دوباره از ابتدا شروع کنید."
            )
 
        return value
 
 
# ─────────────────────────────────────────────────
#  Phone change — step 3
# ─────────────────────────────────────────────────
 
class ChangePhoneVerifyNewSerializer(serializers.Serializer):
    """
    Validates the OTP sent to the NEW phone.
    On success the view updates phone_number and sets is_verified=True.
    """
 
    otp = serializers.CharField(min_length=6, max_length=6)
 
    def validate_otp(self, value):
        user = self.context["request"].user
 
        # Old phone must have been verified first
        if not cache.get(phone_verified_key(user.pk)):
            raise serializers.ValidationError(
                "ابتدا کد تایید شماره قدیمی را وارد کنید."
            )
 
        stored_otp = cache.get(phone_new_otp_key(user.pk))
        if stored_otp is None:
            raise serializers.ValidationError(
                "کد تایید منقضی شده است. دوباره درخواست دهید."
            )
        if stored_otp != value.strip():
            raise serializers.ValidationError("کد تایید اشتباه است.")
 
        # Ensure the new phone number is still in Redis
        if not cache.get(phone_new_key(user.pk)):
            raise serializers.ValidationError(
                "جلسه تغییر شماره منقضی شده است. دوباره از ابتدا شروع کنید."
            )
 
        return value
 
