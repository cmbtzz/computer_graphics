//VTK::System::Dec
in vec4 vertexMC;
in vec3 normalMC;
in vec2 lab4UV;
uniform mat4 MCDCMatrix, MCVCMatrix;
uniform mat3 normalMatrix;
out vec3 positionVC, normalVC;
out vec2 uv;
void main() {
    positionVC=(MCVCMatrix*vertexMC).xyz;
    normalVC=normalMatrix*normalMC;
    uv=lab4UV;
    gl_Position=MCDCMatrix*vertexMC;
}
