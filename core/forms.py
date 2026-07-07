from django import forms
from django.forms import inlineformset_factory
from .models import Session, CourseGroup, Student, Enrollment, Room, CourseGroupSchedule, Level, LevelCategory, TeacherLeave, TeacherAvailability


class StudentForm(forms.ModelForm):
    """Form for creating and editing students"""
    
    class Meta:
        model = Student
        fields = ['name', 'phone', 'parent_name', 'parent_contact', 'date_of_birth', 'address', 'level', 'main_school', 'is_active', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nom complet de l\'élève'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Téléphone de l\'élève',
                'type': 'tel'
            }),
            'parent_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nom du parent/tuteur'
            }),
            'parent_contact': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Téléphone du parent',
                'type': 'tel',
                'required': True
            }),
            'date_of_birth': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Adresse',
                'rows': 3
            }),
            'level': forms.Select(attrs={
                'class': 'form-select',
            }),
            'main_school': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Établissement principal'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Notes supplémentaires',
                'rows': 3
            }),
        }
    
    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError('Le nom de l\'élève est requis')
        return name
    
    def clean_parent_contact(self):
        phone = self.cleaned_data.get('parent_contact', '').strip()
        if not phone:
            raise forms.ValidationError('Le téléphone du parent est requis')
        return phone


class EnrollmentForm(forms.ModelForm):
    """Form for enrolling students in course groups"""
    
    course_group = forms.ModelChoiceField(
        queryset=CourseGroup.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Groupe de cours'
    )
    
    class Meta:
        model = Enrollment
        fields = ['course_group', 'is_active']
        widgets = {
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }


class CourseGroupForm(forms.ModelForm):
    """Form for creating and editing course groups (classes)"""
    
    class Meta:
        model = CourseGroup
        fields = ['name', 'subject', 'level', 'monthly_price', 'teacher', 'whatsapp_group_link', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom du groupe'}),
            'subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Matière'}),
            'level': forms.Select(attrs={'class': 'form-select'}),
            'monthly_price': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Prix mensuel (DH)'}),
            'teacher': forms.Select(attrs={'class': 'form-select'}),
            'whatsapp_group_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'Ex: https://chat.whatsapp.com/...'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    # def __init__(self, *args, **kwargs):
    #     super().__init__(*args, **kwargs)
    #     self.fields['level'].required = False

class LevelForm(forms.ModelForm):
    class Meta:
        model = Level
        fields = ['name', 'category']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom du niveau'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
        }


# Inline FormSet for managing schedules
CourseGroupScheduleFormSet = inlineformset_factory(
    CourseGroup,
    CourseGroupSchedule,
    fields=['day', 'start_time', 'end_time', 'room'],
    extra=1,
    can_delete=True,
    widgets={
        'day': forms.Select(attrs={'class': 'form-select'}),
        'start_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
        'end_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
        'room': forms.Select(attrs={'class': 'form-select'}),
    }
)


class SessionForm(forms.ModelForm):
    room = forms.ModelChoiceField(
        queryset=Room.objects.filter(is_active=True),
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Salle"
    )

    class Meta:
        model = Session
        fields = ['group', 'date', 'start_time', 'end_time', 'room', 'status', 'notes']
        widgets = {
            'group': forms.Select(attrs={'class': 'form-select'}),
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'start_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'end_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Notes...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Non-blocking warnings surfaced to the UI (do not prevent save)
        self.warnings = []

    def clean(self):
        cleaned_data = super().clean()
        group = cleaned_data.get('group')
        date = cleaned_data.get('date')
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')
        room = cleaned_data.get('room')

        if start_time and end_time and end_time <= start_time:
            raise forms.ValidationError("L'heure de fin doit être postérieure à l'heure de début.")

        if date and start_time and end_time and room:
            # --- Room conflict check ---
            conflicts = Session.objects.filter(date=date, room=room).exclude(status='CANCELLED')
            if self.instance and self.instance.pk:
                conflicts = conflicts.exclude(pk=self.instance.pk)

            for s in conflicts:
                if (start_time < s.end_time and end_time > s.start_time):
                    raise forms.ValidationError(
                        f"Conflit de salle : La salle '{room.name}' est déjà réservée par le groupe '{s.group.name}' "
                        f"de {s.start_time.strftime('%H:%M')} à {s.end_time.strftime('%H:%M')}."
                    )

        if group and group.teacher:
            teacher = group.teacher

            # --- Teacher conflict check (double-booking) ---
            if date and start_time and end_time:
                teacher_conflicts = Session.objects.filter(
                    date=date, group__teacher=teacher
                ).exclude(status='CANCELLED')
                if self.instance and self.instance.pk:
                    teacher_conflicts = teacher_conflicts.exclude(pk=self.instance.pk)
                for s in teacher_conflicts:
                    if (start_time < s.end_time and end_time > s.start_time):
                        raise forms.ValidationError(
                            f"Conflit de professeur : Le professeur '{teacher.name}' est déjà affecté au groupe '{s.group.name}' "
                            f"de {s.start_time.strftime('%H:%M')} à {s.end_time.strftime('%H:%M')}."
                        )

            # ----------------------------------------------------------------
            # HARD BLOCK — Teacher is on approved leave on the session date
            # ----------------------------------------------------------------
            if date:
                active_leave = TeacherLeave.objects.filter(
                    teacher=teacher,
                    start_date__lte=date,
                    end_date__gte=date,
                ).first()
                if active_leave:
                    raise forms.ValidationError(
                        f"⛔ Le professeur « {teacher.name} » est en congé "
                        f"({active_leave.get_leave_type_display()}) "
                        f"du {active_leave.start_date.strftime('%d/%m/%Y')} "
                        f"au {active_leave.end_date.strftime('%d/%m/%Y')}. "
                        f"Veuillez choisir une autre date ou un professeur remplaçant."
                    )

            # ----------------------------------------------------------------
            # SOFT WARNING — Session time falls outside availability windows
            # ----------------------------------------------------------------
            if date and start_time and end_time:
                DAY_MAP = {0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'}
                day_code = DAY_MAP[date.weekday()]

                availabilities = TeacherAvailability.objects.filter(
                    teacher=teacher, day=day_code
                )
                if availabilities.exists():
                    # Check hard unavailable slots (is_available=False)
                    for ua in availabilities.filter(is_available=False):
                        if start_time < ua.end_time and end_time > ua.start_time:
                            self.warnings.append(
                                f"⚠️ {teacher.name} est marqué indisponible le "
                                f"{ua.get_day_display()} de {ua.start_time.strftime('%H:%M')} "
                                f"à {ua.end_time.strftime('%H:%M')}."
                            )

                    # Check available slots — warn if session doesn’t fit any
                    available_slots = list(availabilities.filter(is_available=True))
                    if available_slots:
                        fits = any(
                            start_time >= av.start_time and end_time <= av.end_time
                            for av in available_slots
                        )
                        if not fits:
                            slots_display = ", ".join(
                                f"{av.start_time.strftime('%H:%M')}–{av.end_time.strftime('%H:%M')}"
                                for av in available_slots
                            )
                            self.warnings.append(
                                f"⚠️ Le créneau {start_time.strftime('%H:%M')}–{end_time.strftime('%H:%M')} "
                                f"dépasse les plages de disponibilité autorisées de {teacher.name} "
                                f"({slots_display})."
                            )

        return cleaned_data
