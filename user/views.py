import random
import string
import logging
from django.conf import settings
from rest_framework import status
from .tasks import send_otp_sms
from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import AllowAny, IsAuthenticated
from .serializers import (
    SignInSerializer,
    RegisterSerializer,
    RequestOTPSerializer,
    VerifyOTPSerializer,
    UserSerializer,
    ProfileSerializer,
    ChangePasswordRequestSerializer,
    ChangePasswordConfirmSerializer,
    ChangePhoneRequestSerializer,
    ChangePhoneVerifyOldSerializer,
    ChangePhoneVerifyNewSerializer,
    pwd_otp_key, pwd_throttle_key,
    phone_old_otp_key, phone_new_otp_key,
    phone_new_key, phone_verified_key, phone_throttle_key,
    _otp_key,
    _throttle_key,

)


# ──────────────────────────────────────────────
#  Registration
# ──────────────────────────────────────────────
 
class RegisterView(APIView):
    """
    POST /api/auth/register/
 
    Body:
        {
            "username":     "johndoe",
            "phone_number": "09123456789",
            "password":     "secret123",
            "password2":    "secret123",
            "gender":       "M"
        }
 
    Success (201):
        {
            "detail": "ثبت نام موفق. کد تایید به شماره شما ارسال شد.",
            "user": { "id": 1, "username": "johndoe", ... }
        }
 
    ── Next step for the client ──────────────────────────────────────────
    The user is created with is_verified=False.
    Client must complete the OTP flow to be able to sign in:
      1. POST /api/auth/otp/request/  { "phone_number": "09123456789" }
      2. POST /api/auth/otp/verify/   { "phone_number": "...", "otp": "..." }
    """
 
    permission_classes = [AllowAny]
 
    def post(self, request, *args, **kwargs):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
 
        # Automatically kick off OTP so the user doesn't need a second request
        from django.core.cache import cache
        from .tasks import send_otp_sms
        from .serializers import _otp_key, _throttle_key
        from django.conf import settings
        import random, string
 
        OTP_EXPIRY_SECONDS   = getattr(settings, "OTP_EXPIRY_SECONDS",   120)
        OTP_THROTTLE_SECONDS = getattr(settings, "OTP_THROTTLE_SECONDS",  60)
 
        phone = str(user.phone_number)
        otp   = "".join(random.choices(string.digits, k=6))
 
        cache.set(_otp_key(phone),      otp,  timeout=OTP_EXPIRY_SECONDS)
        cache.set(_throttle_key(phone), "1",  timeout=OTP_THROTTLE_SECONDS)
        send_otp_sms.delay(phone, otp)
 
        return Response(
            {
                "detail": "ثبت نام موفق. کد تایید به شماره شما ارسال شد.",
                "user":   UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )
 
 
# ──────────────────────────────────────────────
#  Sign In
# ──────────────────────────────────────────────
 
class SignInView(APIView):
    """
    POST /api/auth/sign-in/
 
    Body:
        {
            "username": "johndoe",
            "password": "secret123"
        }
 
    Success (200):
        {
            "access":  "<access token>",
            "refresh": "<refresh token>",
            "user": { ... }
        }
 
    Error (400):
        { "detail": "نام کاربری یا رمز عبور اشتباه است." }
        { "detail": "شماره تلفن شما تایید نشده است." }   ← unverified users blocked here
    """
 
    permission_classes = [AllowAny]
 
    def post(self, request, *args, **kwargs):
        serializer = SignInSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
 
        refresh = RefreshToken.for_user(user)
 
        return Response(
            {
                "access":  str(refresh.access_token),
                "refresh": str(refresh),
                "user":    UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )
 



logger = logging.getLogger(__name__)
OTP_EXPIRY_SECONDS   = getattr(settings, "OTP_EXPIRY_SECONDS",   120)
OTP_THROTTLE_SECONDS = getattr(settings, "OTP_THROTTLE_SECONDS",  60)
# How long the verified-old-phone flag and new-phone value stay alive
PHONE_SESSION_SECONDS = getattr(settings, "PHONE_CHANGE_SESSION_SECONDS", 300)

OTP_KEY_PREFIX = "otp:"  

def _generate_otp(length: int = 6) -> str:
    """Return a zero-padded numeric OTP of `length` digits."""
    return "".join(random.choices(string.digits, k=length))


# ──────────────────────────────────────────────
#  Step 1 — Request OTP
# ──────────────────────────────────────────────

class RequestOTPView(APIView):
    """
    POST /user/auth/otp/request/

    Body:
        { "phone": "09123456789" }

    Success (200):
        { "detail": "OTP sent successfully." }

    Error (400):
        { "phone": ["..."] }
    """

    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = RequestOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone_number = serializer.validated_data["phone_number"]

        otp = _generate_otp()
        ttl = getattr(settings, "OTP_EXPIRY_SECONDS", 120)  # default: 2 minutes

        # Store OTP in Redis with TTL — auto-expires, no manual cleanup needed
        cache.set(f"{OTP_KEY_PREFIX}{phone_number}", otp, timeout=ttl)

        # Dispatch SMS task asynchronously via RabbitMQ → Celery worker
        send_otp_sms.delay(phone_number, otp)

        logger.info("OTP queued for %s (TTL=%ds)", phone_number, ttl)

        return Response(
            {"detail": "OTP sent successfully."},
            status=status.HTTP_200_OK,
        )


# ──────────────────────────────────────────────
#  Step 2 — Verify OTP
# ──────────────────────────────────────────────

class VerifyOTPView(APIView):
    """
    POST /api/auth/otp/verify/

    Body:
        { "phone": "09123456789", "otp": "481920" }

    Success (200):
        {
            "refresh": "<refresh token>",
            "access":  "<access token>",
            "user": { "id": 1, "phone": "09123456789" }
        }

    Error (400):
        { "otp": ["Invalid OTP code."] }
    """

    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]

        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "refresh": str(refresh),
                "access":  str(refresh.access_token),
                "user": {
                    "id":    user.pk,
                    "phone": user.phone_number,
                },
            },
            status=status.HTTP_200_OK,
        )


# ─────────────────────────────────────────────────
#  Profile view / edit
# ─────────────────────────────────────────────────
 
class ProfileView(APIView):
    """
    GET  /api/profile/   → returns profile data
    PATCH /api/profile/  → partial update (username, first_name, last_name, email, gender)
    """
 
    permission_classes = [IsAuthenticated]
 
    def get(self, request):
        serializer = ProfileSerializer(request.user, context={"request": request})
        return Response(serializer.data)
 
    def patch(self, request):
        serializer = ProfileSerializer(
            request.user,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
 
 
# ─────────────────────────────────────────────────
#  Password change — step 1
# ─────────────────────────────────────────────────
 
class ChangePasswordRequestView(APIView):
    """
    POST /api/profile/change-password/request/
 
    Body:    { "current_password": "..." }
    Success: { "detail": "کد تایید به شماره شما ارسال شد." }
 
    Validates the current password, then sends an OTP to the user's phone.
    """
 
    permission_classes = [IsAuthenticated]
 
    def post(self, request):
        serializer = ChangePasswordRequestSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
 
        user  = request.user
        phone = str(user.phone_number)
        otp   = _generate_otp()
 
        cache.set(pwd_otp_key(user.pk),      otp,  timeout=OTP_EXPIRY_SECONDS)
        cache.set(pwd_throttle_key(user.pk), "1",  timeout=OTP_THROTTLE_SECONDS)
 
        send_otp_sms.delay(phone, otp)
        logger.info("Password-change OTP queued for user %s", user.pk)
 
        return Response(
            {"detail": "کد تایید به شماره شما ارسال شد."},
            status=status.HTTP_200_OK,
        )
 
 
# ─────────────────────────────────────────────────
#  Password change — step 2
# ─────────────────────────────────────────────────
 
class ChangePasswordConfirmView(APIView):
    """
    POST /api/profile/change-password/confirm/
 
    Body:    { "otp": "481920", "new_password": "...", "new_password2": "..." }
    Success: { "detail": "رمز عبور با موفقیت تغییر کرد." }
 
    Validates OTP + new password, then applies the change and clears Redis keys.
    """
 
    permission_classes = [IsAuthenticated]
 
    def post(self, request):
        serializer = ChangePasswordConfirmSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
 
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
 
        # One-time use — delete OTP immediately
        cache.delete(pwd_otp_key(user.pk))
 
        logger.info("Password changed for user %s", user.pk)
 
        return Response(
            {"detail": "رمز عبور با موفقیت تغییر کرد."},
            status=status.HTTP_200_OK,
        )
 
 
# ─────────────────────────────────────────────────
#  Phone change — step 1
# ─────────────────────────────────────────────────
 
class ChangePhoneRequestView(APIView):
    """
    POST /api/profile/change-phone/request/
 
    Body:    { "new_phone_number": "09181234567" }
    Success: { "detail": "کد تایید به شماره فعلی شما ارسال شد." }
 
    Stores the desired new phone in Redis, then sends OTP to the OLD phone.
    """
 
    permission_classes = [IsAuthenticated]
 
    def post(self, request):
        serializer = ChangePhoneRequestSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
 
        user      = request.user
        new_phone = str(serializer.validated_data["new_phone_number"])
        old_phone = str(user.phone_number)
        otp       = _generate_otp()
 
        # Store the intended new phone so later steps can retrieve it
        cache.set(phone_new_key(user.pk),      new_phone, timeout=PHONE_SESSION_SECONDS)
        cache.set(phone_old_otp_key(user.pk),  otp,       timeout=OTP_EXPIRY_SECONDS)
        cache.set(phone_throttle_key(user.pk), "1",       timeout=OTP_THROTTLE_SECONDS)
 
        # OTP goes to the OLD phone — user proves they still own it
        send_otp_sms.delay(old_phone, otp)
        logger.info("Phone-change step-1 OTP queued for user %s → old phone", user.pk)
 
        return Response(
            {"detail": "کد تایید به شماره فعلی شما ارسال شد."},
            status=status.HTTP_200_OK,
        )
 
 
# ─────────────────────────────────────────────────
#  Phone change — step 2
# ─────────────────────────────────────────────────
 
class ChangePhoneVerifyOldView(APIView):
    """
    POST /api/profile/change-phone/verify-old/
 
    Body:    { "otp": "481920" }
    Success: { "detail": "شماره قدیمی تایید شد. کد تایید به شماره جدید ارسال شد." }
 
    Validates OTP on old phone, then sends OTP to the NEW phone.
    """
 
    permission_classes = [IsAuthenticated]
 
    def post(self, request):
        serializer = ChangePhoneVerifyOldSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
 
        user      = request.user
        new_phone = cache.get(phone_new_key(user.pk))
        otp       = _generate_otp()
 
        # Consume old OTP immediately
        cache.delete(phone_old_otp_key(user.pk))
 
        # Mark old phone as verified + send OTP to new phone
        cache.set(phone_verified_key(user.pk), "1",  timeout=PHONE_SESSION_SECONDS)
        cache.set(phone_new_otp_key(user.pk),  otp,  timeout=OTP_EXPIRY_SECONDS)
 
        send_otp_sms.delay(new_phone, otp)
        logger.info("Phone-change step-2 OTP queued for user %s → new phone", user.pk)
 
        return Response(
            {"detail": "شماره قدیمی تایید شد. کد تایید به شماره جدید ارسال شد."},
            status=status.HTTP_200_OK,
        )
 
 
# ─────────────────────────────────────────────────
#  Phone change — step 3
# ─────────────────────────────────────────────────
 
class ChangePhoneVerifyNewView(APIView):
    """
    POST /api/profile/change-phone/verify-new/
 
    Body:    { "otp": "739201" }
    Success: { "detail": "شماره تلفن با موفقیت تغییر کرد.", "phone_number": "+989181234567" }
 
    Validates OTP on new phone, updates phone_number, clears all Redis keys.
    """
 
    permission_classes = [IsAuthenticated]
 
    def post(self, request):
        serializer = ChangePhoneVerifyNewSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
 
        user      = request.user
        new_phone = cache.get(phone_new_key(user.pk))
 
        # Apply the change
        user.phone_number = new_phone
        user.is_verified  = True
        user.save(update_fields=["phone_number", "is_verified"])
 
        # Clean up every Redis key for this flow
        for key_fn in [
            phone_new_key, phone_old_otp_key, phone_new_otp_key,
            phone_verified_key, phone_throttle_key,
        ]:
            cache.delete(key_fn(user.pk))
 
        logger.info("Phone updated for user %s → %s", user.pk, new_phone)
 
        return Response(
            {
                "detail":       "شماره تلفن با موفقیت تغییر کرد.",
                "phone_number": new_phone,
            },
            status=status.HTTP_200_OK,
        )
