import com.sun.source.tree.ClassTree;
import com.sun.source.tree.CompilationUnitTree;
import com.sun.source.tree.ExpressionTree;
import com.sun.source.tree.IdentifierTree;
import com.sun.source.tree.MemberSelectTree;
import com.sun.source.tree.MethodInvocationTree;
import com.sun.source.tree.MethodTree;
import com.sun.source.tree.Tree;
import com.sun.source.tree.VariableTree;
import com.sun.source.util.JavacTask;
import com.sun.source.util.TreePathScanner;
import com.sun.source.util.Trees;
import java.io.File;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import java.nio.file.Path;
import javax.tools.JavaCompiler;
import javax.tools.JavaFileObject;
import javax.tools.StandardJavaFileManager;
import javax.tools.ToolProvider;

/** Emits source-level method calls as TSV; no project dependencies or classpath needed. */
public class SourceCalls {
    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            throw new IllegalArgumentException("Pass Java source files");
        }
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        try (StandardJavaFileManager files = compiler.getStandardFileManager(null, null, null)) {
            Iterable<? extends JavaFileObject> sources = files.getJavaFileObjectsFromFiles(
                    Arrays.stream(args).map(File::new).toList());
            JavacTask task = (JavacTask) compiler.getTask(null, files, null,
                    Arrays.asList("-proc:none"), null, sources);
            Trees trees = Trees.instance(task);
            System.out.println("caller\treceiver\tcallee\tlocation");
            for (CompilationUnitTree unit : task.parse()) {
                new TreePathScanner<Void, Void>() {
                    String className;
                    String methodName;
                    Map<String, String> fields = new HashMap<>();

                    @Override
                    public Void visitClass(ClassTree tree, Void unused) {
                        String oldClass = className;
                        Map<String, String> oldFields = fields;
                        className = tree.getSimpleName().toString();
                        fields = new HashMap<>();
                        for (Tree member : tree.getMembers()) {
                            if (member instanceof VariableTree field) {
                                fields.put(field.getName().toString(), field.getType().toString());
                            }
                        }
                        super.visitClass(tree, unused);
                        className = oldClass;
                        fields = oldFields;
                        return null;
                    }

                    @Override
                    public Void visitMethod(MethodTree tree, Void unused) {
                        String oldMethod = methodName;
                        methodName = tree.getName().toString();
                        super.visitMethod(tree, unused);
                        methodName = oldMethod;
                        return null;
                    }

                    @Override
                    public Void visitMethodInvocation(MethodInvocationTree tree, Void unused) {
                        if (className != null && methodName != null) {
                            String receiver;
                            String callee;
                            ExpressionTree select = tree.getMethodSelect();
                            if (select instanceof MemberSelectTree member) {
                                receiver = member.getExpression().toString();
                                callee = member.getIdentifier().toString();
                            } else if (select instanceof IdentifierTree identifier) {
                                receiver = "this";
                                callee = identifier.getName().toString();
                            } else {
                                receiver = "?";
                                callee = select.toString();
                            }
                            String field = receiver.startsWith("this.")
                                    ? receiver.substring(5) : receiver;
                            if (receiver.equals("this")) receiver = className;
                            else if (fields.containsKey(field)) receiver = fields.get(field);
                            long position = trees.getSourcePositions().getStartPosition(unit, tree);
                            long line = unit.getLineMap().getLineNumber(position);
                            Path source = Path.of(unit.getSourceFile().toUri());
                            Path location = Path.of("").toAbsolutePath().relativize(source);
                            System.out.printf("%s.%s\t%s\t%s\t%s:%d%n",
                                    className, methodName, receiver, callee,
                                    location, line);
                        }
                        return super.visitMethodInvocation(tree, unused);
                    }
                }.scan(unit, null);
            }
        }
    }
}
