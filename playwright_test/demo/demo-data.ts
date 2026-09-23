/**
 * Demo Data & Constants for School ERP Product Walkthrough Video.
 * Uses deterministic, realistic Moroccan school context data.
 */

export interface DemoConfigData {
  school: {
    name: string;
    tagline: string;
    city: string;
  };
  adminUser: {
    username: string;
    password: string;
    fullName: string;
    role: string;
  };
  demoStudent: {
    existingName: string;
    newStudent: {
      name: string;
      phone: string;
      parentName: string;
      parentContact: string;
    };
  };
  demoTeacher: {
    name: string;
    subject: string;
    hourlyRate: string;
  };
  demoCourse: {
    name: string;
    monthlyPrice: string;
  };
  demoPayment: {
    studentName: string;
    amount: string;
    method: string;
  };
  sections: Array<{
    id: string;
    number: string;
    title: string;
    subtitle: string;
  }>;
}

export const DEMO_DATA: DemoConfigData = {
  school: {
    name: 'Groupe Scolaire Atlas',
    tagline: 'Excellence & Réussite Pédagogique',
    city: 'Casablanca',
  },
  adminUser: {
    username: process.env.DEMO_USERNAME || 'admin',
    password: process.env.DEMO_PASSWORD || '1234',
    fullName: 'Direction Pédagogique',
    role: 'Administrateur Général',
  },
  demoStudent: {
    existingName: 'Amine Mansouri',
    newStudent: {
      name: 'Yassine Bennani (Démo)',
      phone: '0661223344',
      parentName: 'M. Bennani',
      parentContact: '0661998877',
    },
  },
  demoTeacher: {
    name: 'Prof. Karim Idrissi',
    subject: 'Mathématiques',
    hourlyRate: '150',
  },
  demoCourse: {
    name: 'Mathématiques 3AC - Groupe A',
    monthlyPrice: '400',
  },
  demoPayment: {
    studentName: 'Amine Mansouri',
    amount: '400',
    method: 'CASH',
  },
  sections: [
    {
      id: '01-login',
      number: '01',
      title: 'Authentification Sécurisée',
      subtitle: 'Accès au portail administratif de gestion scolaire',
    },
    {
      id: '02-dashboard',
      number: '02',
      title: 'Cockpit & Tableau de Bord',
      subtitle: 'Indicateurs clés, recettes du mois et alertes opérationnelles',
    },
    {
      id: '03-students',
      number: '03',
      title: 'Gestion des Élèves',
      subtitle: 'Dossiers scolaires, inscriptions aux groupes et fiches élèves',
    },
    {
      id: '04-teachers',
      number: '04',
      title: 'Corps Enseignant & RH',
      subtitle: 'Gestion des professeurs, disponibilités, congés et paie',
    },
    {
      id: '05-courses',
      number: '05',
      title: 'Offre Pédagogique & Niveaux',
      subtitle: 'Groupes de cours, tarifs mensuels et cycles scolaires',
    },
    {
      id: '06-rooms',
      number: '06',
      title: 'Infrastructures & Salles',
      subtitle: 'Capacité d’accueil, équipements multimédias et climatisation',
    },
    {
      id: '07-schedule',
      number: '07',
      title: 'Emploi du Temps Interactif',
      subtitle: 'Planning hebdomadaire intelligent et détection de conflits',
    },
    {
      id: '08-attendance',
      number: '08',
      title: 'Sessions du Jour & Présences',
      subtitle: 'Pointage rapide des présences et suivi des absences',
    },
    {
      id: '09-cashier',
      number: '09',
      title: 'Caisse & Encaissement',
      subtitle: 'Paiement des cotisations, suivi des impayés et reçus officiels',
    },
    {
      id: '10-analytics',
      number: '10',
      title: 'Analytiques & Reporting',
      subtitle: 'Rapports financiers, taux de présence et exports PDF/CSV',
    },
    {
      id: '11-whatsapp',
      number: '11',
      title: 'Centre de Communication WhatsApp',
      subtitle: 'Rappels de paiement, alertes d’absence et annonces groupées',
    },
    {
      id: '12-settings',
      number: '12',
      title: 'Paramètres du Système',
      subtitle: 'Configuration de l’établissement et personnalisation',
    },
    {
      id: '13-logout',
      number: '13',
      title: 'Clôture de Session',
      subtitle: 'Déconnexion sécurisée de la plateforme ERP',
    },
  ],
};
