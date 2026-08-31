#include <iostream>
using namespace std;
long long a,b,p;
long long fastpow(long long a,long long b,long long mod)
{
    long long res = 1;
    a %= mod;
    while(b > 0){
   		if(b & 1){
   			res = (res * a) % mod;
	   	}
	   	a = a * a % mod;
	   	b >>= 1;
    }
    return res;
}
int main()
{
	cin >> a >> b >> p;
	cout << a << "^" << b << " mod " << p << "=";
	cout << fastpow(a,b,p);
	return 0;
}
