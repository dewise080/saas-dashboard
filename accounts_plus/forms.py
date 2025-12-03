from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password


class EmailRegistrationForm(forms.ModelForm):
    email = forms.EmailField(label="Email", required=True)
    password1 = forms.CharField(
        label="Password", strip=False, widget=forms.PasswordInput, validators=[validate_password]
    )
    password2 = forms.CharField(
        label="Confirm password", strip=False, widget=forms.PasswordInput
    )

    class Meta:
        model = User
        fields = ("email",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.update(
            {"class": "form-control", "placeholder": "Email address"}
        )
        self.fields["password1"].widget.attrs.update(
            {"class": "form-control", "placeholder": "Password"}
        )
        self.fields["password2"].widget.attrs.update(
            {"class": "form-control", "placeholder": "Confirm password"}
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(username=email).exists() or User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        cleaned = super().clean()
        pwd1 = cleaned.get("password1")
        pwd2 = cleaned.get("password2")
        if pwd1 and pwd2 and pwd1 != pwd2:
            self.add_error("password2", "Passwords do not match.")
        return cleaned

    def save(self, commit=True):
        email = self.cleaned_data["email"].strip().lower()
        password = self.cleaned_data["password1"]
        user = User(username=email, email=email)
        user.set_password(password)
        if commit:
            user.save()
        return user
