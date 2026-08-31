#include <bits/stdc++.h>
using namespace std;
long long int jc(long long int n){
	if(n==1||n==0)return long long int(1);
	else return n*jc(n-1);
}
int main()
{
	long long int n;
	cin>>n;
	cout<<n<<"!="<<jc(n);
	return 0;
}
