from django import forms
from django.forms import inlineformset_factory
from .models import Session, CourseGroup, Student, Enrollment, Room, CourseGroupSchedule, Level, LevelCategory, Teacher, TeacherLeave, TeacherAvailability


class CourseGroupMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        schedules_str = ", ".join(
            f"{sch.get_day_display()} {sch.start_time.strftime('%H:%M')}"
            for sch in obj.schedules.all()
        )
        level_str = obj.levels_display
        if schedules_str:
            return f"{obj.name} ({level_str}) - {schedules_str}"
        return f"{obj.name} ({level_str})"


class StudentForm(forms.ModelForm):
    """Form for creating and editing students"""
    create_payment = forms.BooleanField(
        required=False,
        label="Créer un paiement après l'inscription"
    )
    
    groups = CourseGroupMultipleChoiceField(
        queryset=CourseGroup.objects.filter(is_active=True).prefetch_related('schedules', 'level'),
        required=False,
        widget=forms.SelectMultiple(attrs={
            'class': 'form-select select2',
            'multiple': 'multiple'
        }),
        label="Inscrire aux groupes"
    )
    
    class Meta:
        model = Student
        fields = ['name', 'phone', 'parent_name', 'parent_contact', 'parent_contact_2', 'date_of_birth', 'address', 'level', 'main_school', 'is_active', 'notes']
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
            'parent_contact_2': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Téléphone parent 2 (optionnel)',
                'type': 'tel',
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
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            active_group_ids = self.instance.enrollment_set.filter(
                is_active=True
            ).values_list('course_group_id', flat=True)
            self.fields['groups'].initial = CourseGroup.objects.filter(id__in=active_group_ids)
            
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

    def clean_parent_contact_2(self):
        phone = self.cleaned_data.get('parent_contact_2', '').strip()
        return phone

    def clean(self):
        cleaned_data = super().clean()
        groups = cleaned_data.get('groups')
        if groups:
            schedules = []
            for g in groups:
                for sch in g.schedules.all():
                    schedules.append((g, sch))
            
            for i in range(len(schedules)):
                for j in range(i + 1, len(schedules)):
                    g1, sch1 = schedules[i]
                    g2, sch2 = schedules[j]
                    if sch1.day == sch2.day:
                        if (sch1.start_time < sch2.end_time and sch1.end_time > sch2.start_time):
                            self.add_error('groups', 
                                f"Conflit d'horaire détecté entre '{g1.name}' et '{g2.name}' "
                                f"le {sch1.get_day_display()} ({sch1.start_time.strftime('%H:%M')}-{sch1.end_time.strftime('%H:%M')} vs {sch2.start_time.strftime('%H:%M')}-{sch2.end_time.strftime('%H:%M')})."
                            )
        return cleaned_data
    
    def get_groups_display(self):
        """Course groups grouped by level (with level id), for the custom picker UI."""
        if self.is_bound:
            raw = self.data.getlist('groups') if hasattr(self.data, 'getlist') else self.data.get('groups', [])
            checked_ids = {int(i) for i in raw if str(i).isdigit()}
        elif self.instance and self.instance.pk:
            checked_ids = set(
                self.instance.enrollment_set.filter(is_active=True).values_list('course_group_id', flat=True)
            )
        else:
            checked_ids = set()

        groups = self.fields['groups'].queryset.select_related('level').prefetch_related('schedules', 'levels')

        by_level = {}  # key: (level_id_str, level_name) -> list of group dicts
        for g in groups:
            schedules = [
                {
                    'day': sch.get_day_display(),
                    'start': sch.start_time.strftime('%H:%M'),
                    'end': sch.end_time.strftime('%H:%M'),
                }
                for sch in g.schedules.all()
            ]
            group_item = {
                'id': g.id,
                'name': g.name,
                'levels_display': g.levels_display,
                'schedules': schedules,
                'checked': g.id in checked_ids,
            }
            group_levels = list(g.levels.all())
            if not group_levels and g.level:
                group_levels = [g.level]

            if group_levels:
                for lvl in group_levels:
                    key = (str(lvl.id), lvl.name)
                    existing_ids = {item['id'] for item in by_level.get(key, [])}
                    if g.id not in existing_ids:
                        by_level.setdefault(key, []).append(group_item)
            else:
                key = ('', 'Sans niveau')
                by_level.setdefault(key, []).append(group_item)

        # "Sans niveau" last, others sorted by name
        ordered = dict(sorted(by_level.items(), key=lambda kv: (kv[0][0] == '', kv[0][1])))
        return ordered
        
    def save(self, commit=True):
        student = super().save(commit=commit)
        if commit:
            selected_groups = self.cleaned_data.get('groups', [])
            current_enrollments = Enrollment.objects.filter(student=student)
            current_group_ids = set(current_enrollments.values_list('course_group_id', flat=True))
            selected_group_ids = set(g.id for g in selected_groups)
            
            # Delete enrollments that are no longer selected
            current_enrollments.exclude(course_group_id__in=selected_group_ids).delete()
            
            # Create new enrollments
            for group in selected_groups:
                if group.id not in current_group_ids:
                    Enrollment.objects.create(
                        student=student,
                        course_group=group,
                        is_active=True
                    )
        return student


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
    levels = forms.ModelMultipleChoiceField(
        queryset=Level.objects.all().select_related('category'),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select select2', 'multiple': 'multiple'}),
        label="Niveaux académiques"
    )
    
    class Meta:
        model = CourseGroup
        fields = ['name', 'subject', 'levels', 'monthly_price', 'teacher', 'whatsapp_group_link', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom du groupe'}),
            'subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Matière'}),
            'monthly_price': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Prix mensuel (DH)'}),
            'teacher': forms.Select(attrs={'class': 'form-select'}),
            'whatsapp_group_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'Ex: https://chat.whatsapp.com/...'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['levels'].initial = self.instance.levels.all()

    def save(self, commit=True):
        group = super().save(commit=commit)
        if commit:
            first_lvl = group.levels.first()
            if first_lvl and group.level != first_lvl:
                group.level = first_lvl
                CourseGroup.objects.filter(pk=group.pk).update(level=first_lvl)
        return group


class LevelForm(forms.ModelForm):
    class Meta:
        model = Level
        fields = ['name', 'category', 'order', 'next_level']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom du niveau'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ordre (ex: 1, 2, 3...)'}),
            'next_level': forms.Select(attrs={'class': 'form-select'}),
        }


# Inline FormSet for managing schedules
CourseGroupScheduleFormSet = inlineformset_factory(
    CourseGroup,
    CourseGroupSchedule,
    fields=['day', 'start_time', 'end_time', 'room'],
    extra=0,
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


class TeacherForm(forms.ModelForm):
    """Form for creating and editing teachers"""

    class Meta:
        model = Teacher
        fields = [
            'name', 'phone', 'email',
            'payment_method', 'hourly_rate', 'payment_percentage', 'session_rate',
            'is_active',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom complet'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Téléphone', 'type': 'tel'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email (optionnel)'}),
            'payment_method': forms.Select(attrs={'class': 'form-select', 'id': 'id_payment_method'}),
            'hourly_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'payment_percentage': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '100'}),
            'session_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('payment_method')
        if method == 'HOURLY' and not cleaned_data.get('hourly_rate'):
            self.add_error('hourly_rate', "Le tarif horaire est requis pour ce mode de paiement.")
        if method == 'PERCENTAGE' and cleaned_data.get('payment_percentage') is None:
            self.add_error('payment_percentage', "La part des gains (%) est requise pour ce mode de paiement.")
        if method == 'SESSION' and not cleaned_data.get('session_rate'):
            self.add_error('session_rate', "Le tarif par session est requis pour ce mode de paiement.")
        return cleaned_data

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['is_active'].initial = True


class LevelCategoryForm(forms.ModelForm):
    """Form for creating and editing level categories"""

    class Meta:
        model = LevelCategory
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Lycée, Collège, Primaire…',
            }),
        }


class TeacherAvailabilityForm(forms.ModelForm):
    """Inline form for a single teacher availability slot"""

    class Meta:
        model = TeacherAvailability
        fields = ['day', 'start_time', 'end_time', 'is_available']
        widgets = {
            'day': forms.Select(attrs={'class': 'form-select'}),
            'start_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'end_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'is_available': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class TeacherLeaveForm(forms.ModelForm):
    """Form for a teacher leave period"""

    class Meta:
        model = TeacherLeave
        fields = ['start_date', 'end_date', 'leave_type', 'notes']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'end_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'leave_type': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Raison ou détails optionnels…',
            }),
        }


class SystemSettingsForm(forms.Form):
    # 1. Établissement & Identité
    SCHOOL_NAME = forms.CharField(
        label="Nom du centre",
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control form-control-lg', 'placeholder': 'Ex: Centre Scolaire'})
    )
    SCHOOL_SUBTITLE = forms.CharField(
        label="Slogan / Activité",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Soutien Scolaire & Langues'})
    )
    SCHOOL_ADDRESS = forms.CharField(
        label="Adresse",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Adresse complète...'})
    )
    SCHOOL_PHONE = forms.CharField(
        label="Numéro(s) de téléphone",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 0661000000 / 0522000000'})
    )
    SCHOOL_EMAIL = forms.EmailField(
        label="Adresse email de contact",
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'contact@centre.com'})
    )

    # 2. Finances & Reçus
    CURRENCY_SYMBOL = forms.CharField(
        label="Devise / Symbole monétaire",
        required=True,
        initial="DH",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: DH, MAD, $, €'})
    )
    RECEIPT_FOOTER_THANK_YOU = forms.CharField(
        label="Message d'impression au bas des reçus",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Merci pour votre confiance !'})
    )
    LATE_PAYMENT_GRACE_DAYS = forms.IntegerField(
        label="Jours d'échéance autorisés (Retard de paiement)",
        min_value=0,
        required=True,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    ENABLE_PRORATION = forms.BooleanField(
        label="Calculer au prorata le 1er mois pour les inscriptions en cours de mois",
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    # 3. Notifications WhatsApp
    WHATSAPP_AUTO_ABSENCE_NOTIFICATIONS = forms.BooleanField(
        label="Envoyer un message WhatsApp automatique aux parents en cas d'absence",
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    WHATSAPP_SESSION_NOTIFICATIONS_ENABLED = forms.BooleanField(
        label="Notifier les élèves/parents en cas de changement d'horaire ou de salle",
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    WHATSAPP_AUTO_GROUP_INVITE_ON_FIRST_PAYMENT = forms.BooleanField(
        label="Envoyer automatiquement le lien du groupe WhatsApp lors du premier paiement",
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    # 4. Borne Kiosque Élèves
    KIOSK_TIMEOUT = forms.IntegerField(
        label="Secondes d'inactivité avant retour à l'écran d'accueil du kiosque",
        min_value=5,
        required=True,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    KIOSK_SEARCH_ENABLED = forms.BooleanField(
        label="Autoriser les élèves à chercher leur nom sur la borne d'accueil",
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    # 5. Enseignants
    DEFAULT_TEACHER_PAYMENT_METHOD = forms.ChoiceField(
        label="Mode de paiement par défaut pour les nouveaux professeurs",
        choices=[
            ('SESSION', 'Tarif par session (séance)'),
            ('HOURLY', 'Tarif par heure (taux horaire)'),
            ('PERCENTAGE', 'Pourcentage des gains du groupe'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )


