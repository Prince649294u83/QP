export const departments = [
  "Computer Science & Engineering",
  "Information Science & Engineering",
  "Artificial Intelligence & Machine Learning",
  "Electronics & Communication Engineering",
  "Electrical & Electronics Engineering",
  "Mechanical Engineering",
  "Civil Engineering"
];

export const subjects = {
  "Artificial Intelligence & Machine Learning": [
    { code: "21AI51", name: "Machine Learning" },
    { code: "21AI52", name: "Deep Learning" },
    { code: "21AI53", name: "Natural Language Processing" },
    { code: "21AI54", name: "Computer Vision" },
    { code: "21AI55", name: "Data Structures and Algorithms" }
  ]
};

export const questionBank = [
  {
    id: "q1",
    text: "Explain the concept of overfitting in machine learning. How can it be prevented?",
    subject: "Machine Learning",
    subjectCode: "21AI51",
    co: "CO2",
    bloomLevel: "L2",
    difficulty: "Medium",
    marks: 5,
    module: 1
  },
  {
    id: "q2",
    text: "Apply the backpropagation algorithm to update weights in a 3-layer neural network.",
    subject: "Machine Learning",
    subjectCode: "21AI51",
    co: "CO3",
    bloomLevel: "L3",
    difficulty: "Hard",
    marks: 10,
    module: 2
  },
  {
    id: "q3",
    text: "Define precision, recall, and F1-score. Calculate these metrics for a given confusion matrix.",
    subject: "Machine Learning",
    subjectCode: "21AI51",
    co: "CO1",
    bloomLevel: "L2",
    difficulty: "Medium",
    marks: 5,
    module: 1
  },
  {
    id: "q4",
    text: "Design a CNN architecture for image classification of CIFAR-10 dataset.",
    subject: "Deep Learning",
    subjectCode: "21AI52",
    co: "CO4",
    bloomLevel: "L6",
    difficulty: "Hard",
    marks: 10,
    module: 3
  },
  {
    id: "q5",
    text: "Compare supervised, unsupervised, and reinforcement learning with examples.",
    subject: "Machine Learning",
    subjectCode: "21AI51",
    co: "CO1",
    bloomLevel: "L4",
    difficulty: "Medium",
    marks: 5,
    module: 1
  },
  {
    id: "q6",
    text: "Illustrate the working of the K-Means clustering algorithm with a suitable example.",
    subject: "Machine Learning",
    subjectCode: "21AI51",
    co: "CO2",
    bloomLevel: "L3",
    difficulty: "Medium",
    marks: 10,
    module: 4
  },
  {
    id: "q7",
    text: "Discuss the architecture of a Transformer model and its significance in NLP.",
    subject: "Natural Language Processing",
    subjectCode: "21AI53",
    co: "CO3",
    bloomLevel: "L2",
    difficulty: "Medium",
    marks: 10,
    module: 3
  },
  {
    id: "q8",
    text: "Evaluate the performance of Support Vector Machines with different kernels on a linearly inseparable dataset.",
    subject: "Machine Learning",
    subjectCode: "21AI51",
    co: "CO5",
    bloomLevel: "L5",
    difficulty: "Hard",
    marks: 10,
    module: 2
  },
  {
    id: "q9",
    text: "What is Word2Vec? Explain its architecture.",
    subject: "Natural Language Processing",
    subjectCode: "21AI53",
    co: "CO2",
    bloomLevel: "L1",
    difficulty: "Easy",
    marks: 5,
    module: 2
  },
  {
    id: "q10",
    text: "Formulate a dynamic programming solution for the Traveling Salesperson Problem.",
    subject: "Data Structures and Algorithms",
    subjectCode: "21AI55",
    co: "CO4",
    bloomLevel: "L6",
    difficulty: "Hard",
    marks: 10,
    module: 5
  }
];

export const historyData = [
  {
    id: "PPR-2023-001",
    subject: "Machine Learning",
    examType: "IAT-1",
    semester: "5th",
    generatedOn: "2023-10-12",
    status: "Downloaded"
  },
  {
    id: "PPR-2023-002",
    subject: "Deep Learning",
    examType: "IAT-2",
    semester: "6th",
    generatedOn: "2023-11-20",
    status: "Generated"
  },
  {
    id: "PPR-2023-003",
    subject: "Data Structures and Algorithms",
    examType: "End-Sem",
    semester: "4th",
    generatedOn: "2023-12-05",
    status: "Downloaded"
  }
];
