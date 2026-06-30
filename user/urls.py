from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)
from .views import (
    SignInView,
    RequestOTPView,
    VerifyOTPView,
    RegisterView,
    ProfileView,
    ChangePasswordRequestView,
    ChangePasswordConfirmView,
    ChangePhoneRequestView,
    ChangePhoneVerifyOldView,
    ChangePhoneVerifyNewView,

)

urlpatterns = [
    path('token/',                      TokenObtainPairView.as_view(),        name='token_obtain_pair'),
    path('token/refresh/',              TokenRefreshView.as_view(),           name='token_refresh'),
    path('token/verify/',               TokenVerifyView.as_view(),            name='token_verify'),
    path("auth/register/",              RegisterView.as_view(),               name="register"),
    path("auth/sign-in/",               SignInView.as_view(),                 name="sign-in"),
    path("auth/otp/request/",           RequestOTPView.as_view(),             name="otp-request"),
    path("auth/otp/verify/",            VerifyOTPView.as_view(),              name="otp-verify"),
    path("profile",                     ProfileView.as_view(),                name="profile"),
    path("change-password/request/",    ChangePasswordRequestView.as_view(),  name="change-password-request"),
    path("change-password/confirm/",    ChangePasswordConfirmView.as_view(),  name="change-password-confirm"),
    path("change-phone/request/",       ChangePhoneRequestView.as_view(),     name="change-phone-request"),
    path("change-phone/verify-old/",    ChangePhoneVerifyOldView.as_view(),   name="change-phone-verify-old"),
    path("change-phone/verify-new/",    ChangePhoneVerifyNewView.as_view(),   name="change-phone-verify-new"),
]