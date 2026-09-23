export const TEST_USERS = {
  admin: {
    username: 'admin',
    password: 'Password123!', // or 1234
    fallbackPassword: '1234',
    email: 'admin@school-erp.com',
    role: 'SUPERUSER',
  },
  testAdmin: {
    username: 'test_admin',
    password: 'Password123!',
    email: 'testadmin@school-erp.com',
    role: 'SUPERUSER',
  },
  manager: {
    username: 'test_manager',
    password: 'Password123!',
    email: 'manager@school-erp.com',
    role: 'ACADEMIC_MANAGER',
  },
  scheduler: {
    username: 'test_scheduler',
    password: 'Password123!',
    email: 'scheduler@school-erp.com',
    role: 'SCHEDULER',
  },
  teacher: {
    username: 'test_teacher_user',
    password: 'Password123!',
    email: 'teacher@school-erp.com',
    role: 'TEACHER',
  },
  regular: {
    username: 'test_regular_user',
    password: 'Password123!',
    email: 'regular@school-erp.com',
    role: 'STUDENT',
  },
};

export const TEST_DATA = {
  rooms: {
    room1: 'Salle Test A101',
    room2: 'Salle Test B202',
  },
  levels: {
    college: '3ème Année Collège Test',
    lycee: '1ère Année Bac Test',
  },
  teachers: {
    teacher1: 'Prof. Karim Idrissi',
    teacher2: 'Prof. Meriem Alaoui',
  },
  courseGroups: {
    maths: 'Mathématiques 3AC - Groupe A',
    physics: 'Physique-Chimie 1BAC - Groupe B',
  },
  students: {
    stu1: {
      code: 'STU-E2E-001',
      firstName: 'Amine',
      lastName: 'Mansouri',
      phone: '0600112233',
    },
    stu2: {
      code: 'STU-E2E-002',
      firstName: 'Salma',
      lastName: 'Berrada',
      phone: '0622334455',
    },
    stu3: {
      code: 'STU-E2E-003',
      firstName: 'Youssef',
      lastName: 'El Fassi',
      phone: '0644556677',
    },
  },
};
