import { useState } from "react";
import { ManageClasses } from "./ManageClasses.jsx";
import { ManageStudents } from "./ManageStudents.jsx";

// Management navigation: classes ↔ students of a class.
export function Manage() {
  const [klass, setKlass] = useState(null);

  if (!klass) return <ManageClasses onOpenClass={setKlass} />;
  return <ManageStudents klass={klass} onBack={() => setKlass(null)} />;
}
