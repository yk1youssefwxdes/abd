import django_filters
from django import forms
from django.db.models import Q

from .models import Student, CourseGroup, Teacher, Room, Session, Level


class StudentFilter(django_filters.FilterSet):
    q = django_filters.CharFilter(
        method='filter_q', 
        label='Recherche', 
        widget=forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Nom, matricule, téléphone, parent ou école...'
        })
    )
    
    payment_status = django_filters.ChoiceFilter(
        method='filter_payment_status',
        label='Statut de paiement',
        choices=[
            ('', '-- Tous les statuts --'),
            ('paid', '✓ Payé'),
            ('unpaid', '✗ Impayé / Incomplet'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    course_group = django_filters.ModelChoiceFilter(
        field_name='enrollments',
        queryset=CourseGroup.objects.filter(is_active=True),
        label='Groupe de cours',
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        empty_label='-- Tous les groupes --'
    )
    
    level = django_filters.ModelChoiceFilter(
        queryset=Level.objects.all(),
        label='Niveau',
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='-- Tous les niveaux --'
    )

    is_active = django_filters.BooleanFilter(
        field_name='is_active', 
        label='Actif', 
        widget=forms.Select(
            choices=[('', 'Tous'), (True, 'Actifs'), (False, 'Inactifs')],
            attrs={'class': 'form-select'}
        )
    )

    class Meta:
        model = Student
        fields = ['q', 'payment_status', 'level', 'course_group', 'is_active']

    def filter_q(self, queryset, name, value):
        """Search across name, matricule, parent name, and contact info"""
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value) | 
            Q(matricule__icontains=value) |
            Q(parent_contact__icontains=value) | 
            Q(parent_contact_2__icontains=value) |
            Q(parent_name__icontains=value) |
            Q(phone__icontains=value) |
            Q(main_school__icontains=value)
        )
    
    def filter_payment_status(self, queryset, name, value):
        if not value:
            return queryset

        from django.db.models import Prefetch, Sum
        from django.utils import timezone
        from decimal import Decimal
        from core.utils import calculate_enrollment_expected_fee, PAID_STATUSES
        from core.models import Enrollment, Payment

        current_month = timezone.now().date().replace(day=1)

        enrollments_qs = (
            Enrollment.objects.filter(is_active=True)
            .select_related('course_group')
            .prefetch_related('course_group__schedules')
        )

        students = queryset.prefetch_related(
            Prefetch(
                'enrollment_set',
                queryset=enrollments_qs,
                to_attr='active_enrollments'
            )
        )

        payments_summary = (
            Payment.objects.filter(
                month_covered=current_month,
                status__in=PAID_STATUSES
            )
            .values('student_id')
            .annotate(total_paid=Sum('amount'))
        )

        paid_map = {
            p['student_id']: p['total_paid'] or Decimal('0.00')
            for p in payments_summary
        }

        student_ids = []

        for student in students:
            required = Decimal('0.00')

            for enrollment in student.active_enrollments:
                required += calculate_enrollment_expected_fee(
                    enrollment,
                    current_month
                )

            paid = paid_map.get(student.id, Decimal('0.00'))

            is_paid = (required == 0) or (paid >= required)

            if value == "paid" and is_paid:
                student_ids.append(student.id)
            elif value == "unpaid" and not is_paid:
                # Includes both partial and completely unpaid
                student_ids.append(student.id)

        return queryset.filter(id__in=student_ids)


class CourseGroupFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(
        field_name='name', 
        lookup_expr='icontains', 
        label='Nom', 
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Rechercher un groupe...'
        })
    )
    teacher = django_filters.ModelChoiceFilter(
        queryset=Teacher.objects.filter(is_active=True).order_by('name'), 
        label='Professeur', 
        empty_label='-- Tous les professeurs --',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    room = django_filters.ModelChoiceFilter(
        field_name='schedules__room', 
        queryset=Room.objects.filter(is_active=True).order_by('name'), 
        label='Salle', 
        empty_label='-- Toutes les salles --',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    level = django_filters.ModelChoiceFilter(
        queryset=Level.objects.all(),
        label='Niveau',
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='-- Tous les niveaux --',
        method='filter_by_level'
    )

    def filter_by_level(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(levels=value) | Q(level=value)).distinct()
    is_active = django_filters.BooleanFilter(
        field_name='is_active', 
        label='Actif', 
        widget=forms.Select(
            choices=[('', 'Tous'), (True, 'Actifs'), (False, 'Inactifs')],
            attrs={'class': 'form-select'}
        )
    )

    class Meta:
        model = CourseGroup
        fields = ['name', 'teacher', 'level', 'room', 'is_active']


class TeacherFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(
        field_name='name',
        lookup_expr='icontains',
        label='Nom',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Rechercher un professeur...'
        })
    )

    min_rate = django_filters.NumberFilter(
        field_name='hourly_rate',
        lookup_expr='gte',
        label='Tarif min',
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Tarif minimum (DH)'
        })
    )

    max_rate = django_filters.NumberFilter(
        field_name='hourly_rate',
        lookup_expr='lte',
        label='Tarif max',
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Tarif maximum (DH)'
        })
    )

    is_active = django_filters.BooleanFilter(
        field_name='is_active', 
        label='Actif', 
        widget=forms.Select(
            choices=[('', 'Tous'), (True, 'Actifs'), (False, 'Inactifs')],
            attrs={'class': 'form-select'}
        )
    )

    class Meta:
        model = Teacher
        fields = ['name', 'min_rate', 'max_rate', 'is_active']


class RoomFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(
        field_name='name', 
        lookup_expr='icontains', 
        label='Nom', 
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nom de la salle...'
        })
    )
    
    min_capacity = django_filters.NumberFilter(
        field_name='capacity', 
        lookup_expr='gte', 
        label='Capacité min', 
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Places minimales...'
        })
    )

    is_active = django_filters.BooleanFilter(
        field_name='is_active', 
        label='Actif', 
        widget=forms.Select(
            choices=[('', 'Tous'), (True, 'Actifs'), (False, 'Inactifs')],
            attrs={'class': 'form-select'}
        )
    )

    class Meta:
        model = Room
        fields = ['name', 'min_capacity', 'is_active']


class SessionFilter(django_filters.FilterSet):
    """Enhanced session filter with better options"""
    
    date_after = django_filters.DateFilter(
        field_name='date', 
        lookup_expr='gte', 
        label='Depuis le',
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        })
    )
    
    date_before = django_filters.DateFilter(
        field_name='date', 
        lookup_expr='lte', 
        label='Jusqu\'au',
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        })
    )
    
    room = django_filters.ModelChoiceFilter(
        field_name='room',
        queryset=Room.objects.filter(is_active=True).order_by('name'),
        label='Salle',
        empty_label='-- Toutes les salles --',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    teacher = django_filters.ModelChoiceFilter(
        queryset=Teacher.objects.filter(is_active=True).order_by('name'),
        method='filter_teacher',
        label='Professeur',
        empty_label='-- Tous les professeurs --',
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def filter_teacher(self, queryset, name, value):
        if value:
            return queryset.filter(
                Q(substitute_teacher=value) |
                Q(substitute_teacher__isnull=True, group__teacher=value)
            )
        return queryset
    
    status = django_filters.ChoiceFilter(
        field_name='status',
        label='Statut',
        choices=[
            ('', '-- Tous les statuts --'),
            ('PLANNED', 'Prévue'),
            ('DONE', 'Terminée'),
            ('CANCELLED', 'Annulée'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    group_name = django_filters.CharFilter(
        field_name='group__name',
        lookup_expr='icontains',
        label='Groupe',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Rechercher un groupe...'
        })
    )

    class Meta:
        model = Session
        fields = ['date_after', 'date_before', 'room', 'teacher', 'status', 'group_name']
