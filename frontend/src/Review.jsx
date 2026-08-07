import { useState } from "react";
import { ClassList } from "./ClassList.jsx";
import { ClassOverview } from "./ClassOverview.jsx";
import { StudentDetail } from "./StudentDetail.jsx";

// Review navigation: class → class overview → student detail.
export function Review() {
  const [klass, setKlass] = useState(null);
  const [student, setStudent] = useState(null);

  if (!klass) return <ClassList onSelect={setKlass} />;

  if (!student)
    return (
      <ClassOverview
        klass={klass}
        onSelectStudent={setStudent}
        onBack={() => setKlass(null)}
      />
    );

  return (
    <StudentDetail
      student={student}
      onBack={() => setStudent(null)}
      backLabel={klass.name}
    />
  );
}
