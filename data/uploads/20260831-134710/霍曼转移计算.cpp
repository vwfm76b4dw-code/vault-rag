#include <iostream>
#include <cmath>
using namespace std;
double r1,r2;
const double pi = 3.14159265358979323846;
int main()
{
    cin >> r1 >> r2;
    double Xi = (1 - sqrt(((r1 + r2) * (r1 + r2) * (r1 + r2)) / (8 * (r2 * r2 * r2))) * pi);
    cout << Xi << endl;
    return 0;
}
