#include <bits/stdc++.h>
using namespace std;
bool isp(int n){
	if(n==1||n==0)return false;
	for(int i=2;i*i<=n;i++){
		if(n%i==0)return false;
	}
	return true;
}
int n;
int main()
{
	cin>>n;
	for(int i=4;i<=n;i+=2)
	{
	    for(int j=2;j*2<=i;j++){
			if(isp(j)&&isp(i-j)){
				cout<<i<<"="<<j<<"+"<<i-j<<endl;
				break;
			}
		}
	}
}
